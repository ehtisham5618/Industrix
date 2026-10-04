"""Provenance deduplication must separate capture identity from attribution text."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ingest_reviewed_references import credit_key,event_key,reviewed_region

class ReferenceTests(unittest.TestCase):
    def test_review_is_bound_to_bytes_and_all_class_absence(self):
        row={'reviewed_sha256':'original','all_classes_absent':'true','evidence':'reviewed fixture',
            'reviewer':'test','negative_region':'[0,0,1,1]'}
        self.assertEqual(reviewed_region(row,'original'),[0,0,1,1])
        for change,sha in (({},'modified'),({'all_classes_absent':'false'},'original'),
            ({'evidence':''},'original'),({'negative_region':'[0,0,0,1]'},'original')):
            with self.assertRaises(ValueError):reviewed_region({**row,**change},sha)
    def test_own_work_and_homepages_are_not_capture_identifiers(self):
        for credit in ('<span>Own work</span>','https://julesvernex2.com',''):
            self.assertEqual(credit_key({'credit_html':credit}),'')
        a=credit_key({'credit_html':'<a href="https://www.flickr.com/photos/a/12345/">photo</a>'})
        b=credit_key({'credit_html':'<a href="https://www.flickr.com/photos/a/67890/">photo</a>'})
        self.assertNotEqual(a,b);self.assertTrue(a.endswith('12345'))
    def test_capture_day_and_filename_series_are_conservative(self):
        a={'date_original':'2026-10-04 12:00','artist_html':'A','title':'Cloud 1.jpg'}
        self.assertEqual(event_key(a),event_key({**a,'date_original':'2026-10-04 12:01'}))
        self.assertNotEqual(event_key(a),event_key({**a,'artist_html':'B'}))
        a.update(date_original='',artist_html='')
        self.assertEqual(event_key(a),event_key({**a,'title':'Cloud 2.jpg'}))

if __name__=='__main__':unittest.main()
