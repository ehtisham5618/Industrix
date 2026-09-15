"""Fast logic/probe tests; the genuine 3600-second run remains an integration task."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ESE_CPU3_Soak_Test.analysis import memory_trend,evaluate_dod,thermal_analysis,soak_windows
from ESE_CPU3_Soak_Test.soak import parse_args
from ESE_CPU3_Soak_Test.report import read_rows
from SED_3_Stress_Testing.scripts.resource_monitor import ResourceMonitor,ResourceSample


def series(numbers,key='process_rss_mb'):
    return [dict(soak_elapsed_seconds=i*600,warmup=False,**{key:n}) for i,n in enumerate(numbers)]


class SoakAnalysisTests(unittest.TestCase):
    def test_duration_and_official_cli(self):
        args=parse_args(['--duration','3600','--engine','openvino','--streams','3'])
        self.assertEqual((args.duration,args.streams,args.warmup),(3600,3,60))

    def test_relative_camera_config_resolves_before_long_run(self):
        from ESE_CPU1_Quantization.common import ROOT
        args=parse_args(['--config','SED_1_Multi_Camera/configs/3_cameras.json'])
        self.assertEqual(args.config,ROOT/'SED_1_Multi_Camera/configs/3_cameras.json')

    def test_invalid_duration_and_non_cpu_engine_rejected(self):
        for argv in (['--duration','0'],['--duration','-1'],['--duration','nan'],['--duration','inf'],['--engine','pytorch'],['--streams','2']):
            with self.assertRaises(SystemExit):parse_args(argv)

    def test_stable_memory_is_not_unbounded(self):
        result=memory_trend(series([500,502,501,503,502]),'process_rss_mb')
        self.assertFalse(result['leak_detected'])

    def test_material_continuous_growth_is_flagged(self):
        result=memory_trend(series([500,550,600,650,700]),'process_rss_mb')
        self.assertTrue(result['leak_detected'])

    def test_bounded_cache_growth_then_plateau(self):
        result=memory_trend(series([500,550,600,600,600,600]),'process_rss_mb')
        self.assertFalse(result['leak_detected'])

    def test_python_growth_has_separate_material_threshold(self):
        result=memory_trend(series([1,3,5,7,9],'tracemalloc_current_mb'),'tracemalloc_current_mb',1)
        self.assertTrue(result['leak_detected'])

    def test_insufficient_telemetry_not_claimed_leak_free(self):
        result=memory_trend(series([500]),'process_rss_mb')
        self.assertIsNone(result['leak_detected'])
        self.assertFalse(result['evidence_sufficient'])

    def test_interrupted_or_short_run_cannot_pass(self):
        memory={'rss':{'evidence_sufficient':True,'leak_detected':False}}
        for status,duration in [('incomplete',3600),('completed',60),('failed',3600)]:
            self.assertFalse(evaluate_dod(status,duration,0,memory,50,60,True)['overall_pass'])

    def test_capacity_cannot_replace_operational_throughput(self):
        memory={'rss':{'evidence_sufficient':True,'leak_detected':False}}
        result=evaluate_dod('completed',3600,0,memory,22.5,60,True)
        self.assertFalse(result['throughput_target_met'])
        self.assertTrue(result['inference_capacity_target_met'])
        self.assertFalse(result['overall_pass'])

    def test_throttling_unavailable_with_no_temperature(self):
        result=thermal_analysis([{'cpu_freq_mhz':2500,'cpu_temp_c':None}])
        self.assertFalse(result['temperature_available'])
        self.assertTrue(result['frequency_available'])
        self.assertIsNone(result['throttling_detected'])

    def test_six_windows_do_not_include_warmup(self):
        rows=[dict(soak_elapsed_seconds=i*600+1,warmup=False,sample_interval_seconds=1,evaluated_delta=4) for i in range(6)]
        rows.append(dict(soak_elapsed_seconds=-1,warmup=True))
        windows=soak_windows(rows)
        self.assertEqual(len(windows),6)
        self.assertEqual([w['aggregate_fps'] for w in windows],[4]*6)

    def test_missing_cpu_sensor_apis_are_nonfatal(self):
        monitor=ResourceMonitor(enable_gpu=False,enable_cpu_sensors=True)
        monitor.psutil=SimpleNamespace(cpu_freq=lambda:None)
        sample=ResourceSample(0,0);monitor._sample_cpu_sensors(sample)
        self.assertIsNone(sample.cpu_freq_mhz)
        self.assertIsNone(sample.cpu_temp_c)
        self.assertIn('temperature',monitor.sensor_warnings)

    def test_frequency_probe_exception_is_nonfatal(self):
        monitor=ResourceMonitor(enable_gpu=False,enable_cpu_sensors=True)
        monitor.psutil=SimpleNamespace(cpu_freq=lambda:(_ for _ in ()).throw(NotImplementedError()))
        sample=ResourceSample(0,0);monitor._sample_cpu_sensors(sample)
        self.assertIsNone(sample.cpu_freq_mhz)
        self.assertEqual(monitor.sensor_warnings['frequency'],'NotImplementedError')

    def test_persisted_csv_keeps_missing_temperature_null(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'telemetry.csv';path.write_text('warmup,cpu_temp_c,process_rss_mb\nFalse,,500\n')
            rows=read_rows(path)
            self.assertIsNone(rows[0]['cpu_temp_c']);self.assertEqual(rows[0]['process_rss_mb'],500)
            self.assertEqual(json.loads(json.dumps(rows)),rows)

    def test_missing_engine_never_falls_back_to_pytorch(self):
        from ESE_CPU3_Soak_Test.engine import OpenVINODetector
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'artifact is missing'):
                OpenVINODetector(model_dir=folder)


class RetentionTests(unittest.TestCase):
    def test_resolved_archives_bounded_while_live_incidents_retained(self):
        from SED_2_Alert_Escalation.scripts.factory import create_default_escalation_manager
        from ESE_CPU1_Quantization.common import ROOT
        with tempfile.TemporaryDirectory() as folder:
            manager=create_default_escalation_manager(ROOT,Path(folder)/'events.jsonl',history_limit=3)
            for i in range(10):
                manager.process_violation('camera_'+str(i),'smoke',timestamp=i*10)
                manager.reset_camera('camera_'+str(i),timestamp=i*10+1)
            self.assertLessEqual(len(manager.event_store.events),3)
            self.assertLessEqual(len(manager.event_store.history),3)
            self.assertGreater(manager.event_store.archived_events,0)
            self.assertIn('archived_event',(Path(folder)/'events.jsonl').read_text())
            for i in range(5):manager.process_violation('live_'+str(i),'smoke',timestamp=200)
            self.assertEqual(len(manager.active_events()),5)


if __name__=='__main__':unittest.main()
