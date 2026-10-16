import copy
import json

from django.test import SimpleTestCase


class GMDACompatibilityTests(SimpleTestCase):
    def test_identical_landmarks_have_no_distortion(self):
        features = []
        for i, (x, y) in enumerate(((10, 10), (40, 30), (80, 60)), 1):
            features.append({
                'type': 'Feature',
                'properties': {'id': i, 'SketchAlign': f'S{i}', 'aligned': True},
                'geometry': {'type': 'Polygon', 'coordinates': [[
                    [x, y], [x + 5, y], [x + 5, y + 5], [x, y + 5], [x, y]
                ]]},
            })
        data = {'type': 'FeatureCollection', 'features': features}
        response = self.client.post('/gmda/calculateGMDA/', {
            'basemapdata': json.dumps(data), 'sketchmapdata': json.dumps(data),
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual((result['nTL'], result['nDL']), (3, 3))
        for key in ('DistAcc', 'AngAcc', 'CanAcc'):
            self.assertEqual(result[key], 1)
        for key in ('ScaBias', 'RotBias'):
            self.assertEqual(result[key], 0)

    def test_identical_junctions_have_no_distortion(self):
        features = []
        for i, coordinates in enumerate((
                [[0, 0], [100, 0]], [[100, 0], [200, 0]],
                [[100, 0], [100, 100]], [[200, 0], [200, 100]]), 1):
            features.append({
                'type': 'Feature',
                'properties': {'id': i, 'SketchAlign': f'S{i}',
                               'aligned': True, 'feat_type': 'Street'},
                'geometry': {'type': 'LineString', 'coordinates': coordinates},
            })
        base = {'type': 'FeatureCollection', 'features': features}
        sketch = copy.deepcopy(base)
        for feat in sketch['features']:
            feat['properties']['sid'] = f"S{feat['properties']['id']}"
        response = self.client.post('/gmda/calculateJunctionGMDA/', {
            'basemapdata': json.dumps(base), 'sketchmapdata': json.dumps(sketch),
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['nDL'], 2)
        self.assertEqual(result['DistAcc'], 1)
        self.assertEqual(result['AngAcc'], 1)
        self.assertEqual(len(result['basemapJunctions']['features']), 2)

    def test_endpoints_reject_get(self):
        for path in ('calculateGMDA', 'calculateJunctionGMDA'):
            self.assertEqual(self.client.get(f'/gmda/{path}/').status_code, 405)
