import time
import unittest
from pathlib import Path
import numpy as np

from Confidence_Calibration.scripts.alert_policy import load_policy_config
from CME_OPT3_ByteTrack.pipeline import CameraByteTracker, TrackAwarePolicy, TrackConfirmation
from SED_1_Multi_Camera.scripts.models import CameraConfig, FramePacket, GeofenceConfig
from SED_1_Multi_Camera.scripts.stream_manager import MultiCameraStreamManager
from SED_1_Multi_Camera.scripts.camera_source import SyntheticCameraSource
from SED_2_Alert_Escalation.tests.helpers import make_manager

ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_policy_config(ROOT / 'Confidence_Calibration/configs/calibrated_thresholds.yaml')


def detection(track=7, name='fire', class_id=8, x=20):
    return dict(track_id=track, class_name=name, class_id=class_id, confidence=.9,
                coordinates=dict(x1=x, y1=20, x2=x+60, y2=80))


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.state = TrackConfirmation(CONFIG)

    def feed(self, n, start=0, det=None, cam='a'):
        return [self.state.update(cam, [dict(det or detection())], i, i/10) for i in range(start, start+n)]

    def test_single_eight_and_fourteen_frame_transients(self):
        for n in (1, 8, 14):
            self.state = TrackConfirmation(CONFIG)
            self.assertFalse(any(r['alerts'] for r in self.feed(n)))
            for i in range(n, n+5):
                self.assertFalse(self.state.update('a', [], i, i/10)['alerts'])
            self.assertFalse(self.state.states)

    def test_fifteenth_frame_exactly_once(self):
        out = self.feed(20)
        self.assertEqual([i for i, r in enumerate(out) if r['alerts']], [14])
        self.assertEqual(out[14]['alerts'][0]['track_id'], 7)
        self.assertEqual(out[14]['alerts'][0]['camera_id'], 'a')
        self.assertEqual(out[14]['alerts'][0]['confirmed_at'], 1.4)
        self.assertEqual(out[-1]['calibrated_detections'][0]['confirmation_status'], 'active')

    def test_missing_detection_resets_consecutive(self):
        self.feed(10)
        self.state.update('a', [], 10, 1)
        out = self.feed(14, start=11)
        self.assertFalse(any(r['alerts'] for r in out))
        self.assertEqual(len(self.feed(1, start=25)[0]['alerts']), 1)

    def test_ids_never_combine(self):
        self.feed(8)
        self.assertFalse(any(r['alerts'] for r in self.feed(8, start=8, det=detection(8))))

    def test_cameras_never_combine(self):
        self.feed(10, cam='a')
        self.assertFalse(any(r['alerts'] for r in self.feed(10, cam='b')))

    def test_class_change_resets(self):
        self.feed(10)
        self.assertFalse(any(r['alerts'] for r in self.feed(10, start=10, det=detection(name='smoke', class_id=10))))

    def test_frame_duplicates_rejected_and_raw_skips_are_allowed(self):
        self.feed(1)
        with self.assertRaises(ValueError):
            self.feed(1)
        self.assertEqual(self.state.update('a', [detection()], 100, .1)['calibrated_detections'][0]['persistence_frames'], 2)

    def test_expiration_and_new_incident(self):
        first = self.feed(15)[-1]['alerts'][0]['event_id']
        for i in range(15, 20): self.state.update('a', [], i, i/10)
        second = self.feed(15, start=20)[-1]['alerts'][0]['event_id']
        self.assertNotEqual(first, second)
        self.state.reset()
        self.assertFalse(self.state.states)

    def test_untracked_and_duplicate_boxes_cannot_confirm(self):
        for i in range(15):
            out = self.state.update('a', [detection(None)], i, i/10)
            self.assertFalse(out['alerts'])
        self.state.reset()
        for i in range(8):
            out = self.state.update('a', [detection(), detection()], i, i/10)
            self.assertFalse(out['alerts'])

    def test_real_bytetrack_identity_and_class_isolation(self):
        tracker = CameraByteTracker()
        ids = [tracker.update([detection(), detection(name='smoke', class_id=10)])[0]['track_id'] for _ in range(20)]
        self.assertEqual(len(set(ids)), 1)
        self.assertIsInstance(ids[0], int)
        self.assertEqual(len(tracker.trackers), 2)
        tracker.reset()
        self.assertFalse(tracker.trackers)

    def test_new_camera_does_not_reset_existing_allocator(self):
        a, b = CameraByteTracker(), CameraByteTracker()
        first = a.update([detection()])[0]['track_id']
        second = b.update([detection()])[0]['track_id']
        self.assertNotEqual(first, second)
        self.assertEqual(a.update([detection()])[0]['track_id'], first)

    def test_geofence_exit_resets_candidate(self):
        fence = GeofenceConfig('left', [(0,0),(.5,0),(.5,1),(0,1)], {'fire'})
        camera = CameraConfig('a', 'a', 'test', geofences=[fence])
        policy = TrackAwarePolicy(CONFIG)
        frame = np.zeros((100, 300, 3), dtype=np.uint8)
        for i in range(10): policy.process_camera([detection()], camera, frame, i, i/10)
        policy.process_camera([detection(x=200)], camera, frame, 10, 1)
        result = policy.process_camera([detection()], camera, frame, 11, 1.1)
        self.assertFalse(result['alerts'])
        self.assertLess(result['calibrated_detections'][0]['persistence_frames'], 15)

    def test_real_tracker_to_stream_manager_and_sed2(self):
        cameras = [CameraConfig(c, c, 'test') for c in ('a', 'b')]
        escalation = make_manager()
        manager = MultiCameraStreamManager(cameras, None,
            alert_policy_factory=lambda: TrackAwarePolicy(CONFIG), escalation_manager=escalation)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        for i in range(20):
            for camera in cameras:
                manager._route_result(FramePacket(camera.camera_id, i, i/10, frame, 10), [detection()], .001, .002)
                if i < 14: self.assertFalse(manager.latest_results[camera.camera_id].escalations)
        self.assertEqual(len(manager.active_alerts), 2)
        self.assertEqual(len(escalation.all_events()), 2)
        for event in escalation.all_events():
            self.assertIsInstance(event['metadata']['track_id'], int)
            self.assertEqual(event['metadata']['source'], 'cmeopt3_confirmed')

    def test_two_same_class_tracks_reach_independent_sed2_events(self):
        escalation = make_manager()
        out = None
        for i in range(15):
            out = self.state.update('a', [detection(), detection(8, x=200)], i, i/10)
            escalation.process_frame('a', out['confirmed_violations'], i/10)
        self.assertEqual(len(escalation.all_events()), 2)
        escalation.reset_camera('a', 2)
        self.assertFalse(escalation.active_events())
        self.assertFalse(escalation._active_by_key)

    def test_session_reset_never_inherits_candidate(self):
        policy, camera = TrackAwarePolicy(CONFIG), CameraConfig('a', 'a', 'test')
        for i in range(14): policy.process_camera([detection()], camera, None, i, i/10)
        out = policy.process_camera([detection()], camera, None, 0, 0, session_id=1)
        self.assertFalse(out['alerts'])
        self.assertEqual(out['calibrated_detections'][0]['persistence_frames'], 1)

    def test_actual_two_camera_scheduler_smoke(self):
        class Detector:
            def predict_batch(self, frames): return [[detection()] for _ in frames], .001
        manager = MultiCameraStreamManager([CameraConfig(c,c,'synthetic') for c in ('a','b')], Detector(),
            alert_policy_factory=lambda: TrackAwarePolicy(CONFIG), escalation_manager=make_manager(),
            source_factory=lambda c: SyntheticCameraSource(source_fps=120, max_frames=80))
        manager.start()
        time.sleep(1.2)
        manager.stop()
        self.assertEqual({a['camera_id'] for a in manager.active_alerts}, {'a','b'})
        self.assertTrue(all(not p.manager.states for p in manager.alert_policies.values()))

    def test_low_confidence_never_advances_confirmation(self):
        policy, camera = TrackAwarePolicy(CONFIG), CameraConfig('a','a','test')
        for i in range(20):
            low = {**detection(name='smoke',class_id=10),'confidence':.49}
            result = policy.process_camera([low],camera,None,i,i/10)
            self.assertFalse(result['alerts'])
        self.assertFalse(policy.manager.states)

    def test_no_critical_iot_before_confirmation_and_once_after(self):
        camera = CameraConfig('a','a','test',geofences=[GeofenceConfig('response_zone',
            [(0,0),(1,0),(1,1),(0,1)],{'fire'})])
        escalation = make_manager()
        manager = MultiCameraStreamManager([camera],None,alert_policy_factory=lambda:TrackAwarePolicy(CONFIG),
                                          escalation_manager=escalation)
        frame = np.zeros((100,100,3),dtype=np.uint8)
        for i in range(20):
            manager._route_result(FramePacket('a',i,i/10,frame,10),[detection()],.001,.002)
            self.assertEqual(escalation.dispatcher.relay.status()['trigger_count'],0 if i < 14 else 1)
            self.assertIn('confirmation_status',manager.latest_results['a'].detections[0])

    def test_lost_tracker_prediction_is_not_a_positive_frame(self):
        policy, camera = TrackAwarePolicy(CONFIG), CameraConfig('a','a','test')
        for i in range(10): policy.process_camera([detection()],camera,None,i,i/10)
        result = policy.process_camera([],camera,None,10,1)
        self.assertFalse(result['calibrated_detections'])
        for i in range(11,25):
            result = policy.process_camera([detection()],camera,None,i,i/10)
            self.assertFalse(result['alerts'])

    def test_sed2_absence_cleans_active_identity(self):
        escalation = make_manager()
        for i in range(15): result = self.state.update('a',[detection()],i,i/10)
        escalation.process_frame('a',result['confirmed_violations'],1.4)
        for i in range(15,80):
            out = self.state.update('a',[],i,i/10)
            escalation.process_frame('a',out['confirmed_violations'],i/10)
        self.assertFalse(self.state.states)
        self.assertFalse(escalation.active_events())
        self.assertFalse(escalation._active_by_key)


if __name__ == '__main__': unittest.main()
