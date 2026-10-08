import json
import math
from pathlib import Path
import unittest

from ESE_CPU1_Quantization.common import ROOT,accuracy_delta,digest,source_model
from ESE_CPU1_Quantization.benchmark import latency_summary


class QuantizationCalculations(unittest.TestCase):
    def test_percentage_points_are_not_relative_percentage(self):
        delta=accuracy_delta(0.725,0.720)
        self.assertAlmostEqual(delta['drop_pp'],0.5)
        self.assertTrue(delta['strict_0_8pp_pass'])
        self.assertAlmostEqual(delta['relative_change_pct'],-0.6896551724)

    def test_strict_threshold_and_dod_are_separate(self):
        delta=accuracy_delta(0.78,0.771)
        self.assertFalse(delta['strict_0_8pp_pass'])
        self.assertTrue(delta['dod_1_0pp_pass'])

    def test_no_accuracy_regression_is_valid(self):
        self.assertTrue(accuracy_delta(0.75,0.76)['strict_0_8pp_pass'])

    def test_invalid_accuracy_scale_is_rejected(self):
        for values in ((75,74),(float('nan'),0.5)):
            with self.assertRaises(ValueError):accuracy_delta(*values)

    def test_unmeasured_latency_is_rejected(self):
        for values in ([],[0],[-1],[float('nan')],[float('inf')]):
            with self.assertRaises(ValueError):latency_summary(values,30,2)

    def test_high_latency_tail_is_preserved(self):
        result=latency_summary([10]*199+[1000],30,2)
        self.assertEqual(result['iterations'],200)
        self.assertEqual(result['max_ms'],1000)
        self.assertGreater(result['mean_ms'],result['min_ms'])
        self.assertEqual(result['p95_ms'],10)


class MeasuredQuantizationAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Required integration test: absence of genuine measured evidence is an error.
        cls.report=json.loads((ROOT/'SED_3_Stress_Testing/reports/quant_report.json').read_text())

    def test_actual_map_drop_below_one_percentage_point(self):
        delta=self.report['accuracy']
        self.assertLess((delta['fp32']['map50']-delta['int8']['map50'])*100,1.0)

    def test_exact_training_only_calibration_and_coverage(self):
        import csv
        with (ROOT/'ESE_CPU1_Quantization/reports/calibration_manifest.csv').open(newline='',encoding='utf-8') as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),300)
        self.assertEqual(len({row['image'] for row in rows}),300)
        self.assertEqual({row['split'] for row in rows},{'train'})
        self.assertEqual({int(c) for row in rows for c in row['classes'].split(';') if c},set(range(12)))

    def test_selected_artifact_hashes(self):
        for artifact in self.report['artifacts']['artifacts'].values():
            self.assertEqual(digest(ROOT/artifact['path']),artifact['sha256'])

    def test_current_source_checkpoint_loads_with_twelve_classes(self):
        model=source_model(ROOT/'Backend/best.pt')
        self.assertEqual(len(model.names),12)

    def test_fp16_onnx_loads_and_runs_batch_one_on_cpu(self):
        import numpy as np
        import onnx
        import onnxruntime as ort
        path=ROOT/'Backend/weights/onnx_fp16/best_fp16.onnx'
        graph=onnx.load(str(path));onnx.checker.check_model(graph)
        self.assertTrue(any(item.data_type==onnx.TensorProto.FLOAT16 for item in graph.graph.initializer))
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        session=ort.InferenceSession(str(path),options,providers=['CPUExecutionProvider'])
        output=session.run(None,{session.get_inputs()[0].name:np.zeros((1,3,640,640),np.float32)})[0]
        self.assertEqual(output.shape,(1,16,8400));self.assertTrue(np.isfinite(output).all())

    def test_openvino_int8_loads_and_runs_batch_one_on_cpu(self):
        import numpy as np
        import openvino as ov
        graph=ov.Core().read_model(ROOT/'Backend/weights/openvino_int8/model.xml')
        self.assertTrue(any(op.get_type_name()=='FakeQuantize' for op in graph.get_ops()))
        compiled=ov.Core().compile_model(graph,'CPU',{'PERFORMANCE_HINT':'LATENCY','INFERENCE_NUM_THREADS':2,'NUM_STREAMS':1})
        output=compiled([np.zeros((1,3,640,640),np.float32)])[compiled.output(0)]
        self.assertEqual(output.shape,(1,16,8400));self.assertTrue(np.isfinite(output).all())

    def test_actual_ir_size_below_6_5_decimal_mb(self):
        directory=ROOT/'Backend/weights/openvino_int8'
        size=sum((directory/name).stat().st_size for name in ('model.xml','model.bin'))
        self.assertLess(size,6500000,'Genuine measured size gate; do not suppress this failure')

    def test_combined_ir_size_counts_xml_and_bin(self):
        manifest=self.report['artifacts'];files=manifest['artifacts']
        self.assertEqual(manifest['combined_core_bytes'],files['openvino_xml']['bytes']+files['openvino_bin']['bytes'])
        self.assertEqual(manifest['size_pass'],manifest['combined_core_bytes']<6500000)

    def test_actual_cpu_targets_and_real_int8(self):
        self.assertEqual(self.report['runtime_settings']['onnx_providers'],['CPUExecutionProvider'])
        self.assertEqual(self.report['runtime_settings']['openvino_device'],'CPU')
        self.assertGreater(self.report['artifacts']['nncf_fake_quantize_ops'],0)

    def test_evaluation_protocol_parity(self):
        accuracy=self.report['accuracy']
        for key in ('split','imgsz','batch','conf','iou','max_det','rect'):
            self.assertEqual(accuracy['fp32'][key],accuracy['int8'][key])
        self.assertEqual(accuracy['fp32']['split'],'test')


if __name__=='__main__':unittest.main()
