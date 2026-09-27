"""Ignore unknown regions and unreviewed negative classes during fine-tuning.

Only the negative classification terms are masked. Positive target terms and
the stock YOLO box/DFL terms are unchanged. Geometric augmentations must be off
so source review rectangles map exactly through the deterministic letterbox.
"""
from __future__ import annotations
import json,math
from pathlib import Path
import torch
from ultralytics.utils.loss import v8DetectionLoss
from ultralytics.utils.tal import make_anchors
from ultralytics.models.yolo.world.train import WorldTrainer
from ultralytics.utils.torch_utils import strip_optimizer
from ultralytics.utils import LOGGER


def masked_bce(logits,targets,negative_mask):
    values=torch.nn.functional.binary_cross_entropy_with_logits(logits,targets,reduction='none')
    # A confirmed assigned object supplies the usual single-class contrast at
    # that foreground anchor. Unassigned unknown background supplies no signal.
    foreground=targets.sum(-1,keepdim=True)>0
    return values * (negative_mask | foreground).to(values.dtype)


class ReviewBCE(torch.nn.Module):
    def __init__(self):
        super().__init__();self.negative_mask=None
    def forward(self,logits,targets):
        if self.negative_mask is None:raise RuntimeError('Missing review mask')
        return masked_bce(logits,targets,self.negative_mask)


class FixedClassText:
    """Keep the global class IDs stable for per-class review masks."""
    def __call__(self,labels):
        labels['texts']=[text[0] for text in labels['texts']]
        return labels


class MPSCompatibleAssignment(torch.nn.Module):
    """Run detached target matching on CPU; keep network/loss tensors on MPS.

    PyTorch MPS boolean indexing can return inconsistent selected lengths in
    Ultralytics TAL (upstream issue #22971). Moving the whole no-grad assignment
    boundary avoids both affected indexing sites without changing its math.
    """
    def __init__(self,assigner):
        super().__init__();self.assigner=assigner

    @torch.no_grad()
    def forward(self,*tensors):
        device=tensors[0].device
        if device.type!='mps':return self.assigner(*tensors)
        outputs=self.assigner(*(t.detach().to('cpu') for t in tensors))
        return tuple(t.to(device) for t in outputs)


def letterbox_review_rect(rect,source_hw,target_hw):
    h,w=source_hw; th,tw=target_hw
    ratio=max(th,tw)/max(h,w)
    rh,rw=min(math.ceil(h*ratio),max(th,tw)),min(math.ceil(w*ratio),max(th,tw))
    # Source loader resizes first; LetterBox then uses these integer dimensions.
    scale=min(th/rh,tw/rw)
    left=round((tw-round(rw*scale))/2-.1);top=round((th-round(rh*scale))/2-.1)
    sx,sy=rw/w*scale,rh/h*scale
    x1,y1,x2,y2=rect
    return [x1*sx+left,y1*sy+top,x2*sx+left,y2*sy+top]


class ReviewedDetectionLoss(v8DetectionLoss):
    def __init__(self,model,reviews):
        super().__init__(model);self.reviews=reviews;self.bce=ReviewBCE()
        self.assigner=MPSCompatibleAssignment(self.assigner)

    def loss(self,preds,batch):
        anchors,strides=make_anchors(preds['feats'],self.stride,.5)
        centers=anchors*strides
        bs=preds['scores'].shape[0];nc=preds['scores'].shape[1]
        mask=torch.zeros((bs,len(anchors),nc),dtype=torch.bool,device=self.device)
        for i,path in enumerate(batch['im_file']):
            review=self.reviews[Path(path).stem]
            complete=set(review['complete_classes_outside_unknown'])
            texts=batch['texts'][i]
            for j,name in enumerate(texts):
                if name in complete:mask[i,:,j]=True
            for region in review.get('explicit_negative_regions',[]):
                x1,y1,x2,y2=letterbox_review_rect(region['xyxy'],review['source_hw'],batch['img'].shape[-2:])
                inside=(centers[:,0]>=x1)&(centers[:,0]<=x2)&(centers[:,1]>=y1)&(centers[:,1]<=y2)
                for j,name in enumerate(texts):
                    if name in region['classes']:mask[i,inside,j]=True
            for region in review['unknown_regions']:
                x1,y1,x2,y2=letterbox_review_rect(region['xyxy'],review['source_hw'],batch['img'].shape[-2:])
                inside=(centers[:,0]>=x1)&(centers[:,0]<=x2)&(centers[:,1]>=y1)&(centers[:,1]<=y2)
                mask[i,inside,:]=False
        self.bce.negative_mask=mask
        return super().loss(preds,batch)


class ReviewedWorldTrainer(WorldTrainer):
    def check_resume(self,overrides):
        # Upstream otherwise restores the old data path and 20-epoch target.
        # Preserve checkpoint state while honoring the user's new total and
        # reviewed dataset; save into a new run so old evidence stays intact.
        requested={k:overrides[k] for k in ('data','epochs','project','name','exist_ok') if k in overrides}
        super().check_resume(overrides)
        if self.resume:
            for key,value in requested.items():setattr(self.args,key,value)
            if 'project' in requested and 'name' in requested:
                self.args.save_dir=str(Path(requested['project'])/requested['name'])

    def resume_training(self,ckpt):
        if self.resume:
            completed=ckpt.get('epoch',-1)+1 if ckpt else 0
            if not completed or completed>=self.epochs:
                raise ValueError('Resume requires unfinished checkpoint epochs below the requested total')
            if not ckpt.get('optimizer'):
                raise ValueError('Checkpoint has no optimizer state; refusing to silently restart')
        super().resume_training(ckpt)
        if self.resume:
            expected=len(ckpt['optimizer']['state'])
            actual=len(self.optimizer.state_dict()['state'])
            if actual!=expected or self.start_epoch!=completed:
                raise ValueError('Checkpoint optimizer or epoch state was not restored')
            proof=dict(completed_epochs_before_resume=completed,next_epoch=self.start_epoch+1,
                target_total_epochs=self.epochs,remaining_epochs=self.epochs-completed,
                optimizer_state_entries=actual,checkpoint_optimizer_state_entries=expected,
                ema_updates_restored=self.ema.updates,checkpoint_ema_updates=ckpt.get('updates'),
                data=str(self.args.data),checkpoint=str(self.args.resume),test_set_executed=False)
            (self.save_dir/'resume_state.json').write_text(json.dumps(proof,indent=2))

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in ('mosaic','mixup','copy_paste','degrees','translate','scale','shear','perspective','flipud','fliplr','multi_scale'):
            if getattr(self.args,field,0):raise ValueError(f'{field} must be 0 for source-space review masks')
        review_path=Path(self.args.data).parent/'training_review.json'
        self.review_metadata=json.loads(review_path.read_text())
        self.add_callback('on_train_start',self.install_review_loss)

    def build_dataset(self,img_path,mode='train',batch=None):
        dataset=super().build_dataset(img_path,mode,batch)
        if mode=='train':
            transforms=dataset.transforms.transforms
            for i,transform in enumerate(transforms):
                if type(transform).__name__=='RandomLoadText':transforms[i]=FixedClassText()
        return dataset

    def install_review_loss(self,trainer):
        trainer.model.criterion=ReviewedDetectionLoss(trainer.model,self.review_metadata)

    def validate(self):
        # Partial-label holdouts need a separate reviewed evaluation. This
        # baseline uses training loss for checkpoint bookkeeping only.
        return {}, -float(self.tloss.detach().sum().cpu())

    def final_eval(self):
        for path in (self.last,self.best):
            if path.exists():strip_optimizer(path)
        LOGGER.info('Baseline complete: final-epoch weights retained. No held-out validation or test-set evaluation executed.')
