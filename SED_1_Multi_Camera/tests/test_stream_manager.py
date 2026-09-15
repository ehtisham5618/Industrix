"""Deterministic ring/scheduler/lifecycle checks; no RTSP server or weights."""
import queue
import threading
import time
import unittest
from unittest.mock import patch

from SED_1_Multi_Camera.scripts.models import CameraConfig, FramePacket
from SED_1_Multi_Camera.scripts.ring_buffer import FrameRingBuffer
from SED_1_Multi_Camera.scripts.stream_manager import MultiCameraStreamManager
from SED_1_Multi_Camera.scripts.camera_source import FileCameraSource, SyntheticCameraSource


def packet(i, camera='a'):
    return FramePacket(camera, i, i/30, {'sequence':i}, 30)


class RingTests(unittest.TestCase):
    def test_exact_capacity(self):
        for capacity in (0, 14, 16, 100):
            with self.assertRaises(ValueError):
                FrameRingBuffer(capacity)
        self.assertEqual(FrameRingBuffer().maxsize, 15)

    def test_boundary(self):
        self.assertEqual([i for i in range(8) if FrameRingBuffer.should_select(i)], [0,4])

    def test_hundred_raw_frames_have_25_selected_and_75_skips(self):
        ring=FrameRingBuffer()
        observed=[]
        for i in range(100):
            selected, overrun, _=ring.write(packet(i))
            self.assertFalse(overrun)
            if selected:
                observed.append(ring.get_nowait().frame_id)
            self.assertLessEqual(ring.qsize(),15)
        self.assertEqual(observed,list(range(0,100,4)))
        self.assertEqual(ring.snapshot()['intentional_skips'],75)
        self.assertEqual(ring.snapshot()['true_overruns'],0)

    def test_unread_selected_overwrites_are_true_losses(self):
        ring=FrameRingBuffer()
        for i in range(100): ring.write(packet(i))
        selected=[]
        while not ring.empty(): selected.append(ring.get_nowait().frame_id)
        self.assertEqual(selected,[88,92,96])
        self.assertEqual(ring.snapshot()['true_overruns'],22)
        self.assertEqual(ring.snapshot()['normal_reuses'],63)
        self.assertEqual(ring.snapshot()['max_occupancy'],15)
        self.assertEqual(ring.snapshot()['selected'],ring.snapshot()['reads']+22)

    def test_duplicate_or_reordered_raw_sequences_rejected(self):
        ring=FrameRingBuffer();ring.write(packet(4))
        for i in (4,3):
            with self.assertRaises(ValueError): ring.write(packet(i))

    def test_independent_buffers(self):
        a,b=FrameRingBuffer(),FrameRingBuffer()
        a.write(packet(0,'a'));b.write(packet(0,'b'))
        a.get_nowait()
        self.assertEqual(b.get_nowait().camera_id,'b')
        self.assertEqual(a.snapshot()['reads'],1)

    def test_threaded_producer_consumer_accounting_and_order(self):
        ring=FrameRingBuffer();done=threading.Event();seen=[]
        def produce():
            for i in range(2000): ring.write(packet(i))
            done.set()
        def consume():
            while not done.is_set() or not ring.empty():
                try: seen.append(ring.get_nowait().frame_id)
                except queue.Empty: done.wait(.001)
        producer,consumer=threading.Thread(target=produce),threading.Thread(target=consume)
        consumer.start();producer.start();producer.join(3);consumer.join(3)
        self.assertFalse(producer.is_alive() or consumer.is_alive())
        self.assertEqual(seen,sorted(set(seen)))
        counters=ring.snapshot()
        self.assertEqual(counters['selected'],counters['reads']+counters['true_overruns'])
        self.assertLessEqual(counters['max_occupancy'],15)


class RecordingDetector:
    def __init__(self): self.seen=[]
    def predict_batch(self,frames):
        self.seen.extend(frame['synthetic_frame_id'] for frame in frames)
        return [[] for _ in frames],0


class LifecycleTests(unittest.TestCase):
    def manager(self,source_factory=None,detector=None,micro_batch=True):
        return MultiCameraStreamManager([CameraConfig(c,c,'fake') for c in ('a','b','c')],
            detector or RecordingDetector(),source_factory=source_factory or
            (lambda _:SyntheticCameraSource(source_fps=200,max_frames=100)),micro_batch=micro_batch)

    def wait_finished(self,manager):
        for worker in manager.workers: worker.join(4)
        manager.stop(timeout=4)

    def test_three_workers_all_evaluate_only_phase_zero(self):
        detector=RecordingDetector();manager=self.manager(detector=detector)
        manager.start();self.wait_finished(manager)
        self.assertEqual(len(manager.workers),3)
        for m in manager.metrics.values():
            self.assertEqual((m.captured,m.eligible,m.configured_skips,m.processed),(100,25,75,25))
            self.assertEqual(m.overload_drops,0)
        self.assertTrue(all((i-1)%4==0 for i in detector.seen))
        self.assertFalse(manager.scheduler_thread.is_alive())

    def test_failed_factory_is_isolated(self):
        def source(cfg):
            if cfg.camera_id=='b': raise RuntimeError('source unavailable')
            return SyntheticCameraSource(source_fps=200,max_frames=24)
        manager=self.manager(source);manager.start();self.wait_finished(manager)
        self.assertEqual(manager.metrics['b'].status,'failed')
        self.assertIn('unavailable',manager.metrics['b'].last_error)
        self.assertEqual(manager.metrics['a'].processed,6)
        self.assertEqual(manager.metrics['c'].processed,6)

    def test_blocked_camera_does_not_hold_other_cameras(self):
        entered,release=threading.Event(),threading.Event()
        class Slow(SyntheticCameraSource):
            def read(self):
                entered.set();release.wait(3)
                return False,None
        manager=self.manager(lambda c: Slow() if c.camera_id=='b' else
            SyntheticCameraSource(source_fps=200,max_frames=24))
        try:
            manager.start();self.assertTrue(entered.wait(2))
            manager.workers[0].join(3);manager.workers[2].join(3)
            self.assertEqual(manager.metrics['a'].captured,24)
            self.assertEqual(manager.metrics['c'].captured,24)
        finally:
            release.set();manager.stop()

    def test_stop_restart_uses_fresh_counters_and_rings(self):
        manager=self.manager();manager.start();self.wait_finished(manager)
        manager.start();self.wait_finished(manager)
        self.assertTrue(all(m.captured==100 for m in manager.metrics.values()))
        self.assertTrue(all(q.snapshot()['writes']==100 for q in manager.queues.values()))
        self.assertFalse(any(w.thread.is_alive() for w in manager.workers))

    def test_double_start_rejected(self):
        manager=self.manager();manager.start()
        try:
            with self.assertRaises(RuntimeError): manager.start()
        finally: manager.stop()

    def test_single_frame_batches_rotate_fairly(self):
        manager=self.manager(micro_batch=False)
        for i in range(0,8,4):
            for c,q in manager.queues.items(): q.write(packet(i,c))
        self.assertEqual([manager._next_fair_batch()[0].camera_id for _ in range(6)],
                         ['a','b','c','a','b','c'])

    def test_detector_exception_is_explicit_and_shutdown_joins(self):
        class Broken:
            def predict_batch(self,frames): raise RuntimeError('inference crashed')
        manager=self.manager(detector=Broken());manager.start()
        manager.scheduler_thread.join(4);manager.stop()
        self.assertIn('shared inference/tracking failed',manager.scheduler_error)
        self.assertGreater(sum(m.inference_drops for m in manager.metrics.values()),0)
        self.assertFalse(any(w.thread.is_alive() for w in manager.workers))
        for c,m in manager.metrics.items():
            self.assertEqual(m.eligible,m.processed+m.overload_drops+m.inference_drops)
            self.assertEqual(manager.queues[c].snapshot()['pending_selected'],0)

    def test_blocked_read_shutdown_refuses_overlapping_restart(self):
        entered,release=threading.Event(),threading.Event()
        class Blocked(SyntheticCameraSource):
            def read(self): entered.set();release.wait(4);return False,None
        manager=self.manager(lambda _:Blocked())
        manager.start();self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(RuntimeError): manager.stop(timeout=.01)
            with self.assertRaises(RuntimeError): manager.start()
        finally:
            release.set();manager.stop()
        self.assertFalse(any(w.thread.is_alive() for w in manager.workers))


class SourceTests(unittest.TestCase):
    def test_network_open_failures_reconnect_with_cancelable_backoff(self):
        opened=threading.Event()
        class Network(SyntheticCameraSource):
            is_live=True
            def __post_init__(self):
                super().__post_init__();self.opens=0
            def open(self):
                self.opens+=1
                if self.opens<=2: raise RuntimeError('private source URL')
                super().open();opened.set()
        source=Network(source_fps=100)
        manager=MultiCameraStreamManager([CameraConfig('a','a','fake')],RecordingDetector(),
                                         source_factory=lambda _:source)
        manager.start()
        try:
            self.assertTrue(opened.wait(4))
        finally: manager.stop()
        self.assertEqual(manager.metrics['a'].open_failures,2)
        self.assertEqual(manager.metrics['a'].reconnections,1)
        self.assertNotIn('private',str(manager.statuses()))

    def test_live_read_failure_reopens_and_records_session_change(self):
        reopened=threading.Event()
        class Network(SyntheticCameraSource):
            is_live=True
            def __post_init__(self):
                super().__post_init__();self.opens=0;self.failed=False
            def open(self):
                self.opens+=1
                if self.opens>1: reopened.set()
                super().open()
            def read(self):
                if not self.failed:
                    self.failed=True
                    raise RuntimeError('network interruption')
                return super().read()
        source=Network(source_fps=100)
        manager=MultiCameraStreamManager([CameraConfig('a','a','fake')],RecordingDetector(),
                                         source_factory=lambda _:source)
        manager.start()
        try: self.assertTrue(reopened.wait(3))
        finally: manager.stop()
        self.assertEqual(manager.metrics['a'].decode_failures,1)
        self.assertEqual(manager.metrics['a'].reconnections,1)
        self.assertEqual(manager.metrics['a'].worker_crashes,0)
    def test_rtsp_open_has_native_read_and_open_timeouts(self):
        import cv2
        class Capture:
            def isOpened(self): return True
            def get(self,_): return 30
            def release(self): pass
        with patch.object(cv2,'VideoCapture',return_value=Capture()) as factory:
            source=FileCameraSource('rtsp://example.invalid/live');source.open();source.close()
        self.assertEqual(factory.call_args.args[1],cv2.CAP_FFMPEG)
        self.assertIn(cv2.CAP_PROP_READ_TIMEOUT_MSEC,factory.call_args.args[2])
        self.assertIn(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,factory.call_args.args[2])

    def test_file_loop_increments_session_and_stop_wait_is_cancelled(self):
        import cv2
        class Capture:
            def __init__(self): self.calls=0
            def isOpened(self): return True
            def get(self,_): return 30
            def set(self,*_): pass
            def read(self):
                self.calls+=1
                return (self.calls>1,object())
            def release(self): pass
        with patch.object(cv2,'VideoCapture',return_value=Capture()),patch('pathlib.Path.exists',return_value=True):
            source=FileCameraSource('test.mp4');source.open()
            self.assertTrue(source.read()[0]);self.assertEqual(source.session_generation,1)
            source.stop_event.set();self.assertFalse(source.read()[0]);source.close()

    def test_network_config_not_resolved_as_local_path(self):
        import json,tempfile
        from SED_1_Multi_Camera.scripts.config import load_camera_configs
        # Config normally lives three levels below root; URL must remain untouched.
        with tempfile.TemporaryDirectory() as folder:
            path=__import__('pathlib').Path(folder)/'a'/'b'/'config.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'cameras':{'a':{'source':'rtsp://example.invalid/live'}}}))
            self.assertEqual(load_camera_configs(path)[0].source,'rtsp://example.invalid/live')


class TemporalIntegrationTests(unittest.TestCase):
    def test_15_evaluated_observations_not_15_raw_frames(self):
        import numpy as np
        from CME_OPT3_ByteTrack.pipeline import TrackAwarePolicy
        from Confidence_Calibration.scripts.alert_policy import load_policy_config
        from SED_2_Alert_Escalation.tests.helpers import make_manager
        from pathlib import Path
        root=Path(__file__).resolve().parents[2]
        cfg=load_policy_config(root/'Confidence_Calibration/configs/calibrated_thresholds.yaml')
        detector=RecordingDetector()
        manager=MultiCameraStreamManager([CameraConfig('a','a','fake')],detector,
            alert_policy_factory=lambda:TrackAwarePolicy(cfg),escalation_manager=make_manager())
        frame=np.zeros((100,100,3),dtype=np.uint8)
        hazard=dict(class_id=8,class_name='fire',confidence=.9,
            coordinates=dict(x1=20,y1=20,x2=80,y2=80))
        ring=manager.queues['a'];updates=0
        for raw in range(60):
            p=FramePacket('a',raw,raw/30,frame,30)
            selected,_,_=ring.write(p)
            if selected:
                manager._route_result(ring.get_nowait(),[hazard],.001,.002)
                updates+=1
                if updates<15: self.assertFalse(manager.active_alerts)
        self.assertEqual(updates,15)
        self.assertEqual(len(manager.active_alerts),1)
        self.assertEqual(len(manager.escalation_manager.all_events()),1)
        self.assertEqual(manager.latest_results['a'].frame_id,56)
        self.assertEqual(manager.alert_policies['a'].tracker.calls,15)
        # 15/FPS is the report estimate; first-to-fifteenth span is 14/FPS.
        self.assertAlmostEqual(56/30,14/7.5)


if __name__=='__main__': unittest.main()
