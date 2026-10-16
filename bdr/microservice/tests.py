import copy
import json

from django.test import SimpleTestCase


class BDRCompatibilityTests(SimpleTestCase):
    def assert_translation(self, path, geometries):
        features = [
            {'type': 'Feature', 'geometry': geometry,
             'properties': {'id': i, 'aligned': True, 'SketchAlign': f'S{i}'}}
            for i, geometry in enumerate(geometries, 1)
        ]
        base = {'type': 'FeatureCollection', 'features': features}
        sketch = copy.deepcopy(base)
        for feat in sketch['features']:
            geom = feat['geometry']
            rings = geom['coordinates'] if geom['type'] == 'Polygon' else [geom['coordinates']]
            for ring in rings:
                for point in ring:
                    point[0] += 20
                    point[1] += 30
        response = self.client.post(path, {
            'basemapdata': json.dumps(base), 'sketchmapdata': json.dumps(sketch),
        })
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        for key, expected in {'r': 1, 'DI': 0, 'phi': 1, 'theta': 0,
                              'alpha1': 20, 'alpha2': 30}.items():
            self.assertAlmostEqual(result[key], expected, places=4)

    def test_translated_landmarks_recover_known_transform(self):
        self.assert_translation('/bdr/calculateLandmarksBDR/', [
            {'type': 'Polygon', 'coordinates': [[
                [x, 10], [x + 5, 10], [x + 5, 15], [x, 15], [x, 10]
            ]]} for x in (10, 40, 80)
        ])

    def test_translated_junctions_recover_known_transform(self):
        self.assert_translation('/bdr/calculateJunctionsBDR/', [
            {'type': 'LineString', 'coordinates': coordinates}
            for coordinates in (
                [[0, 0], [100, 0]], [[100, 0], [200, 0]],
                [[100, 0], [100, 100]], [[200, 0], [200, 100]],
            )
        ])
