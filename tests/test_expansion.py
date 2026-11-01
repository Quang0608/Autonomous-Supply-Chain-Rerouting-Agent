import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from expand_maritime_dataset import normalize_country,target_bucket,require_quotas,check_port_limit,rank_bucket

class ExpansionTests(unittest.TestCase):
    def test_us_country_normalization_and_cross_border_bucket(self):
        self.assertEqual(normalize_country("USA"),"US")
        self.assertEqual(normalize_country("United States of America"),"US")
        self.assertEqual(normalize_country("China"),"CN")
        self.assertEqual(normalize_country("South Korea"),"KR")
        self.assertEqual(target_bucket({"Supplier Country":"USA","Customer Country":"Germany"}),(True,False))
        self.assertEqual(target_bucket({"Supplier Country":"China","Customer Country":"Japan"}),(False,True))
        self.assertEqual(target_bucket({"Supplier Country":"USA","Customer Country":"China"}),(True,True))

    def test_overlap_bucket_assignment_is_exclusive(self):
        report={"selected_us_bucket":50,"selected_china_bucket":50,"shortfalls":{"US":0,"China":0}}
        self.assertIsNone(require_quotas(report))

    def test_quota_shortfall_fails_and_port_cap_is_enforced(self):
        with self.assertRaisesRegex(RuntimeError,"Quota shortfall"):
            require_quotas({"selected_us_bucket":49,"selected_china_bucket":50,"shortfalls":{"US":1,"China":0}})
        self.assertTrue(check_port_limit(50,50))
        with self.assertRaisesRegex(ValueError,"ceiling"):
            check_port_limit(51,50)

    def test_edge_selection_order_is_seed_deterministic(self):
        edges=[{"Supplier":"S1","Customer":"C1","Supplier Country":"USA","Customer Country":"Germany","Supplier Industry":"A","Customer Industry":"B"},{"Supplier":"S2","Customer":"C2","Supplier Country":"USA","Customer Country":"Japan","Supplier Industry":"A","Customer Industry":"B"}]
        a=rank_bucket(edges,set(),42);b=rank_bucket(edges,set(),42)
        self.assertEqual(a,b)

if __name__=="__main__":unittest.main()
