"""Resume must honor total epochs and must not silently become fine-tuning."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from reviewed_loss import ReviewedWorldTrainer, WorldTrainer


class ResumeTests(unittest.TestCase):
    def bare(self,total=15):
        trainer=object.__new__(ReviewedWorldTrainer)
        trainer.resume=True;trainer.epochs=total
        trainer.args=SimpleNamespace(data='old/data.yaml',epochs=20,project='old',name='old',save_dir='old/run')
        return trainer

    def test_resume_does_not_restore_old_twenty_epoch_target_or_old_output(self):
        trainer=self.bare()
        with patch.object(WorldTrainer,'check_resume') as upstream:
            trainer.check_resume(dict(data='new/data.yaml',epochs=15,project='new/runs',name='resume',exist_ok=False))
            upstream.assert_called_once()
        self.assertEqual(trainer.args.epochs,15)
        self.assertEqual(trainer.args.data,'new/data.yaml')
        self.assertEqual(Path(trainer.args.save_dir),Path('new/runs/resume'))

    def test_stripped_checkpoint_cannot_fall_back_to_weights_only(self):
        trainer=self.bare()
        with self.assertRaisesRegex(ValueError,'no optimizer state'):
            trainer.resume_training(dict(epoch=7,optimizer=None))

    def test_already_completed_target_cannot_become_extra_epochs(self):
        trainer=self.bare(8)
        with self.assertRaisesRegex(ValueError,'below the requested total'):
            trainer.resume_training(dict(epoch=7,optimizer={'state':{}}))


if __name__=='__main__':unittest.main()
