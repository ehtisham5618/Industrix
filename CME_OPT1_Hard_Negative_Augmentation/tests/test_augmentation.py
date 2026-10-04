"""Meaningful geometry, semantics, leakage guards and deterministic transforms."""
import csv
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Preprocessing/scripts'))
import cv2
import numpy as np
import yaml
from augment_hard_negatives import mosaic, photometric, quality, qualifying, safe_source
from mine_hard_negatives import digest
from validate_yolo_dataset import validate_label_line, validate_dataset
from dataset_statistics import collect_split_stats

class AugmentationTests(unittest.TestCase):
    def setUp(self):
        self.image=np.random.default_rng(1).integers(30,220,(64,80,3),dtype=np.uint8)
    def test_photometric_determinism_and_dimensions(self):
        boxes=[[10,.5,.5,.5,.5]]
        for strategy in ('color_jitter','hsv','chemical_sheen','smoke_overlay'):
            a=photometric(self.image,strategy,np.random.default_rng(42),boxes,10)
            b=photometric(self.image,strategy,np.random.default_rng(42),boxes,10)
            np.testing.assert_array_equal(a,b)
            self.assertEqual(a.shape,self.image.shape); self.assertEqual(a.dtype,np.uint8)
            quality(a,boxes,12); self.assertEqual(boxes,[[10,.5,.5,.5,.5]])
    def test_overlay_refuses_negative_smoke(self):
        with self.assertRaises(ValueError):
            photometric(self.image,'smoke_overlay',np.random.default_rng(1),[],10)
    def test_overlay_stays_inside_existing_smoke_box(self):
        out=photometric(self.image,'smoke_overlay',np.random.default_rng(42),[[10,.5,.5,.5,.5]],10)
        np.testing.assert_array_equal(out[:16],self.image[:16])
        np.testing.assert_array_equal(out[:, :20],self.image[:, :20])
        self.assertTrue(np.any(out[16:48,20:60]!=self.image[16:48,20:60]))
    def test_mosaic_geometry_and_minimum_size(self):
        image,boxes=mosaic([self.image]*4,[[[7,.5,.5,1,1],[10,.5,.5,.001,.001]]]*4,640)
        self.assertEqual(image.shape,(640,640,3));self.assertEqual(len(boxes),4)
        np.testing.assert_allclose(boxes,[[7,.25,.25,.5,.5],[7,.75,.25,.5,.5],
                                         [7,.25,.75,.5,.5],[7,.75,.75,.5,.5]])
    def test_invalid_boxes_and_quality(self):
        for line in ('12 .5 .5 .1 .1','7 nan .5 .1 .1','7 .9 .5 .5 .1','7 .5 .5 0 .1','7 .5 .5 .1'):
            self.assertFalse(validate_label_line(line,12)[0])
        with self.assertRaises(ValueError): quality(np.zeros_like(self.image),[],12)
    def test_split_and_digest_protection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'images/train').mkdir(parents=True); (root/'images/val').mkdir()
            p=root/'images/train/a.png';cv2.imwrite(str(p),self.image)
            row={'source_image':'images/train/a.png','split':'train','source_sha256':digest(p)}
            self.assertEqual(safe_source(root,row),p)
            for change in ({'split':'val'},{'source_image':'images/val/a.png'},{'source_sha256':'wrong'}, {'source_image':'../a.png'}):
                with self.assertRaises(ValueError): safe_source(root,{**row,**change})
    def test_qualifying_requires_review_and_deduplicates(self):
        row={'failure_type':'hard_negative_candidate','verification_status':'verified','verification_evidence':'visual review',
             'reviewer':'tester','ground_truth_present':'false','selected_for_augmentation':'true','source_sha256':'a'}
        self.assertEqual(len(qualifying([row,row])),1)
        for change in ({'verification_status':'pending'},{'verification_evidence':''},{'reviewer':''},{'failure_type':'hard_positive'}):
            self.assertEqual(len(qualifying([{**row,**change}])),0)
    def test_validator_rejects_orphan_and_cross_split_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data.yaml').write_text(yaml.safe_dump({'names':['a'],'nc':1,'train':'images/train','val':'images/val','test':'images/test'}))
            for index,split in enumerate(('train','val','test')):
                (root/'images'/split).mkdir(parents=True);(root/'labels'/split).mkdir(parents=True)
                cv2.imwrite(str(root/'images'/split/'a.png'),np.full((16,16,3),80+index*20,np.uint8))
                (root/'labels'/split/'a.txt').write_text('0 .5 .5 .5 .5\n')
            self.assertTrue(validate_dataset(root))
            (root/'labels/train/orphan.txt').write_text('')
            self.assertFalse(validate_dataset(root));(root/'labels/train/orphan.txt').unlink()
            (root/'images/val/a.png').write_bytes((root/'images/train/a.png').read_bytes())
            self.assertFalse(validate_dataset(root))
            stats=collect_split_stats(root,{'names':['a']})
            self.assertEqual(stats['splits']['train']['images_per_class'][0],1)


    def test_end_to_end_labels_splits_manifest_and_reproducibility(self):
        from mine_hard_negatives import FIELDS, write_manifest
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);root=base/'source'
            names=['baekra','color issues','contamination','cut','gray stitch','selvet','stain',
                   'chemical hazard','fire','no helmet','smoke','water leak']
            root.mkdir(); (root/'data.yaml').write_text(yaml.safe_dump({'names':names,'nc':12,
                'train':'images/train','val':'images/val','test':'images/test'}))
            selected=[]
            strategies=['chemical_sheen','smoke_overlay','mosaic','color_jitter','hsv']
            for split in ('train','val','test'):
                (root/'images'/split).mkdir(parents=True); (root/'labels'/split).mkdir(parents=True)
                for i in range(5 if split=='train' else 1):
                    stem=f'{split}_{i}'
                    path=root/'images'/split/f'{stem}.png'
                    image=np.random.default_rng(i+len(split)*20).integers(30,220,(64,80,3),dtype=np.uint8)
                    cv2.imwrite(str(path),image)
                    cls=[7,10,None,6,7][i] if split=='train' else None
                    (root/'labels'/split/f'{stem}.txt').write_text('' if cls is None else f'{cls} .5 .5 .5 .5\n')
                    if split=='train':
                        row={key:'' for key in FIELDS};row.update(sample_id=stem,source_image=path.relative_to(root).as_posix(),
                            source_sha256=digest(path),split='train',target_class='smoke' if i in (1,2) else 'chemical hazard',
                            failure_type='hard_negative_candidate' if i==2 else 'potential_hard_negative' if i==3 else 'hard_positive',
                            ground_truth_present='False' if i in (2,3) else 'True',selected_for_augmentation='true',
                            verification_status='verified',verification_evidence='fixture reviewed',reviewer='test',augmentation_strategy=strategies[i])
                        selected.append(row)
            manifest=base/'selected.csv';write_manifest(manifest,selected)
            outputs=[]
            script=Path(__file__).resolve().parents[2]/'Preprocessing/scripts/augment_hard_negatives.py'
            for repeat in (1,2):
                out=base/f'out{repeat}';report=base/f'report{repeat}'
                cmd=[sys.executable,str(script),'--dataset',str(root),'--output',str(out),'--manifest',str(manifest),
                     '--reports',str(report),'--count','5','--seed','42']
                result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                outputs.append((report/'augmentation_manifest.csv').read_bytes())
                summary=json.loads((report/'augmentation_summary.json').read_text())
                self.assertEqual(summary['verified_combined_qualifying_examples'],2)
                self.assertEqual(summary['verified_observed_negative_images'],1)
                self.assertEqual(summary['verified_potential_negative_images'],1)
                for split in ('val','test'):
                    self.assertEqual(len(list((out/'images'/split).glob('*'))),1)
                    self.assertEqual(digest(out/'images'/split/f'{split}_0.png'),digest(root/'images'/split/f'{split}_0.png'))
                with (report/'augmentation_manifest.csv').open(encoding='utf-8') as manifest_file:
                    additions=list(csv.DictReader(manifest_file))
                self.assertEqual({r['augmentation_type'] for r in additions},set(strategies))
                for row in additions:
                    if row['augmentation_type']!='mosaic':
                        src=Path(json.loads(row['source_image'])[0]).stem
                        dst=Path(row['output_image']).stem
                        self.assertEqual((root/'labels/train'/f'{src}.txt').read_bytes(),(out/'labels/train'/f'{dst}.txt').read_bytes())
            self.assertEqual(outputs[0],outputs[1])
            # A distinct encoded image with the same Roboflow source name must be blocked too.
            old=root/'images/val/val_0.png'; new=root/'images/val/train_0.rf.other.png'
            old.rename(new);(root/'labels/val/val_0.txt').rename(root/'labels/val/train_0.rf.other.txt')
            blocked=base/'blocked'
            result=subprocess.run([sys.executable,str(script),'--dataset',str(root),'--output',str(blocked),
                '--manifest',str(manifest),'--reports',str(base/'blocked_report'),'--count','5'],
                capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
            self.assertNotEqual(result.returncode,0)
            self.assertIn('overlaps evaluation image/family',result.stderr)
            self.assertFalse(blocked.exists())

if __name__=='__main__': unittest.main()
