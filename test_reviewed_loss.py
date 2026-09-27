import unittest
import torch
from reviewed_loss import masked_bce,letterbox_review_rect,MPSCompatibleAssignment
from ultralytics.utils.tal import TaskAlignedAssigner


class ReviewLossTests(unittest.TestCase):
    def test_unknown_negative_has_no_gradient(self):
        logits=torch.zeros((1,2,2),requires_grad=True)
        target=torch.tensor([[[1.,0.],[0.,0.]]])
        mask=torch.zeros_like(target,dtype=torch.bool)
        masked_bce(logits,target,mask).sum().backward()
        self.assertLess(logits.grad[0,0,0],0)
        self.assertGreater(logits.grad[0,0,1],0)  # known foreground class contrast
        self.assertEqual(logits.grad[0,1,0],0)
        self.assertEqual(logits.grad[0,1,1],0)

    def test_reviewed_background_still_trains(self):
        logits=torch.zeros((1,1,2),requires_grad=True);target=torch.zeros_like(logits)
        mask=torch.tensor([[[True,False]]])
        masked_bce(logits,target,mask).sum().backward()
        self.assertGreater(logits.grad[0,0,0],0);self.assertEqual(logits.grad[0,0,1],0)

    def test_full_review_matches_standard_loss(self):
        logits=torch.tensor([[[.4,-.3],[2.,-2.]]],requires_grad=True)
        target=torch.tensor([[[.7,0.],[0.,.5]]]);mask=torch.ones_like(target,dtype=torch.bool)
        self.assertTrue(torch.allclose(masked_bce(logits,target,mask),torch.nn.functional.binary_cross_entropy_with_logits(logits,target,reduction='none')))

    def test_actual_video_letterbox(self):
        self.assertEqual(letterbox_review_rect([0,0,960,544],[544,960],[640,640]),[0.,138.,640.,501.])


class AssignmentCompatibilityTests(unittest.TestCase):
    @staticmethod
    def inputs(seed,bs=2,na=128,nc=72,ng=12):
        generator=torch.Generator().manual_seed(seed)
        scores=torch.rand((bs,na,nc),generator=generator)
        centers=torch.rand((na,2),generator=generator)*640
        boxes=torch.cat((centers[None].expand(bs,-1,-1)-30,centers[None].expand(bs,-1,-1)+30),-1)
        xy=torch.rand((bs,ng,2),generator=generator)*450
        gt=torch.cat((xy,xy+torch.rand((bs,ng,2),generator=generator)*160+20),-1)
        labels=torch.randint(nc,(bs,ng,1),generator=generator).float()
        mask=torch.rand((bs,ng,1),generator=generator)>.25
        return scores,boxes,centers,labels,gt,mask

    def test_cpu_and_empty_targets_preserve_assignment(self):
        for ng in (0,12):
            args=self.inputs(7,ng=ng)
            expected=TaskAlignedAssigner(num_classes=72)(*args)
            actual=MPSCompatibleAssignment(TaskAlignedAssigner(num_classes=72))(*args)
            for a,b in zip(actual,expected):torch.testing.assert_close(a,b,rtol=0,atol=0)

    @unittest.skipUnless(torch.backends.mps.is_available(),'Requires an actual MPS GPU')
    def test_mps_dense_assignment_matches_cpu_under_changing_masks(self):
        torch.set_num_threads(4)
        wrapped=MPSCompatibleAssignment(TaskAlignedAssigner(num_classes=72))
        reference=TaskAlignedAssigner(num_classes=72)
        # Actual training dimensions; vary padded object counts and nonzero masks.
        for seed in range(20):
            args=self.inputs(seed,bs=16,na=8400,ng=32+seed%7)
            expected=reference(*args)
            actual=wrapped(*(t.to('mps') for t in args))
            for a,b in zip(actual,expected):
                self.assertEqual(a.device.type,'mps')
                torch.testing.assert_close(a.cpu(),b,rtol=0,atol=0)
            self.assertGreater(int(actual[3].sum().cpu()),0)


if __name__=='__main__':unittest.main()
