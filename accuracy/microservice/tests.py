import copy
import json

from django.test import SimpleTestCase


class AccuracyCompatibilityTests(SimpleTestCase):
    def test_identical_maps_preserve_qualitative_relations(self):
        features = []
        for i, x in enumerate((10, 50), 1):
            features.append({
                'type': 'Feature',
                'properties': {'id': i, 'feat_type': 'Landmark',
                               'SketchAlign': [f'S{i}'], 'aligned': True},
                'geometry': {'type': 'Polygon', 'coordinates': [[
                    [x, 10], [x + 5, 10], [x + 5, 15], [x, 15], [x, 10]
                ]]},
            })
        for i, coordinates in enumerate((
                [[0, 0], [100, 0]], [[100, 0], [100, 100]]), 3):
            features.append({
                'type': 'Feature',
                'properties': {'id': i, 'feat_type': 'Street', 'isRoute': 'Yes',
                               'routeOrder': i - 2, 'sketchrouteorder': i - 2,
                               'SketchAlign': [f'S{i}'], 'aligned': True},
                'geometry': {'type': 'LineString', 'coordinates': coordinates},
            })
        base = {'type': 'FeatureCollection', 'features': features}
        sketch = copy.deepcopy(base)
        for feat in sketch['features']:
            feat['properties']['sid'] = f"S{feat['properties']['id']}"
        response = self.client.post('/accuracy/analyzeQualitative/', {
            'sketchFileName': 'test', 'metricFileName': 'test',
            'sketchdata': json.dumps(sketch), 'metricdata': json.dumps(base),
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(len(result['smqcn']['constraint_collection']), 6)
        values = result['qualitative_results']
        self.assertEqual(values['skipped'], {})
        for key in ('correctnessAccuracy_rcc11', 'correctnessAccuracy_streetTop',
                    'correctnessAccuracy_opra', 'correctnessAccuracy_DE9IM',
                    'correctnessAccuracy_LR', 'correctnessAccuracy_LO'):
            self.assertEqual(values[key], 100)
