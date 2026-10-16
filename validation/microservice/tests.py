import json

from django.test import SimpleTestCase
import geopandas as gpd
from shapely.geometry import LineString

from .views import validateRoute


def feature(identifier, geometry, coordinates):
    return {'type': 'Feature', 'properties': {'id': identifier},
            'geometry': {'type': geometry, 'coordinates': coordinates}}


class ValidationCompatibilityTests(SimpleTestCase):
    def test_preview_and_apply_connected_streets(self):
        lines = {'type': 'FeatureCollection', 'features': [
            feature(1, 'LineString', [[0, 0], [100, 0]]),
            feature(2, 'LineString', [[100, 0], [200, 0]]),
        ]}
        payload = {'type': 'metric', 'metricdata': json.dumps(lines)}
        preview = self.client.post('/validation/validate/', payload).json()
        self.assertEqual(len(preview['audit']['merge']), 1)
        self.assertEqual(set(preview['audit']['merge'][0]['merged_from']), {1, 2})
        response = self.client.post('/validation/validate/', {
            **payload, 'action': 'apply',
            'merge': json.dumps(preview['audit']['merge']),
        })
        self.assertEqual(response.status_code, 200)
        features = response.json()['modifiedStreets']['features']
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]['geometry']['coordinates'],
                         [[0, 0], [100, 0], [200, 0]])

    def test_nearby_streets_propose_a_snap(self):
        lines = {'type': 'FeatureCollection', 'features': [
            feature(1, 'LineString', [[0, 0], [100, 0]]),
            feature(2, 'LineString', [[103, 0], [200, 0]]),
        ]}
        response = self.client.post('/validation/validate/', {
            'type': 'metric', 'metricdata': json.dumps(lines),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn([1, 2], response.json()['audit']['snap'])

    def test_landmarks_without_streets_survive_both_map_types(self):
        data = {'type': 'FeatureCollection', 'features': [
            feature(1, 'Polygon', [[[0, 0], [5, 0], [5, 5], [0, 0]]]),
        ]}
        for kind in ('metric', 'sketch'):
            response = self.client.post('/validation/validate/', {
                'type': kind, f'{kind}data': json.dumps(data),
                'action': 'apply', 'alignment': '{}',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['modifiedStreets'], data)

    def test_route_orientation_on_retained_segments(self):
        data = gpd.GeoDataFrame({
            'id': [1, 2],
            'geometry': [LineString([(100, 0), (0, 0)]),
                         LineString([(200, 0), (100, 0)])],
        })
        corrected = validateRoute(data, [1, 2])
        self.assertEqual(list(corrected.geometry.iloc[0].coords), [(0, 0), (100, 0)])
        self.assertEqual(list(corrected.geometry.iloc[1].coords), [(100, 0), (200, 0)])
