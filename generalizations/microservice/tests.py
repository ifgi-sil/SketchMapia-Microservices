import copy
import json
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase
from shapely.geometry import shape

from .views import requestFME
from django.test import RequestFactory


class GeneralizationCompatibilityTests(SimpleTestCase):
    def generalize(self, base, sketch, alignment):
        request = RequestFactory().post('/generalizations/requestFME/', {
            'basedata': json.dumps(base), 'sketchdata': json.dumps(sketch),
            'aligndata': json.dumps(alignment), 'sketchmapName': 'test',
        })
        # The endpoint uses relative files. Keep all writes away from the
        # checked-in examples and any user's analysis outputs.
        with TemporaryDirectory() as directory, chdir(directory):
            Path('generalizedMap').mkdir()
            response = requestFME(request)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def test_checked_in_example_matches_existing_output(self):
        folder = Path(__file__).resolve().parents[1] / 'generalizedMap'
        def load(name):
            return json.loads((folder / name).read_text())
        actual = self.generalize(load('inputbaseMap.json'),
                                 load('inputsketchMap.json'),
                                 load('alignment.json'))
        expected = load('generalizedoutputMap.json')
        self.assertEqual(len(actual['features']), len(expected['features']))
        for observed, reference in zip(actual['features'], expected['features']):
            self.assertEqual(observed['properties'], reference['properties'])
            self.assertTrue(shape(observed['geometry']).equals(shape(reference['geometry'])))

    def test_polygon_generalizations(self):
        base = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'id': i, 'aligned': True},
             'geometry': {'type': 'Polygon', 'coordinates': [[
                 [x, 0], [x + 5, 0], [x + 5, 5], [x, 5], [x, 0]
             ]]}}
            for i, x in enumerate((0, 10))
        ]}
        sketch = copy.deepcopy(base)
        for feat in sketch['features']:
            feat['properties']['sid'] = f"S{feat['properties']['id']}"
        for kind, identifiers, expected_type in (
                ('Amalgamation', [0, 1], 'Polygon'),
                ('Collapse', [0], 'Polygon')):
            with self.subTest(kind=kind):
                alignment = {'1': {
                    'BaseAlign': {'0': identifiers}, 'SketchAlign': {'0': ['S0']},
                    'genType': kind, 'degreeOfGeneralization': 1,
                }, 'checkAlignnum': 2}
                result = self.generalize(base, sketch, alignment)
                generated = [f for f in result['features']
                             if f['properties'].get('genType') == kind]
                self.assertEqual(len(generated), 1)
                self.assertEqual(generated[0]['geometry']['type'], expected_type)
                self.assertTrue(shape(generated[0]['geometry']).is_valid)
                if kind == 'Collapse':
                    # Collapsed points are buffered for display by the endpoint.
                    self.assertAlmostEqual(shape(generated[0]['geometry']).area, 3.14, places=2)

    def test_omission_merge_joins_street_segments(self):
        base = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'id': i, 'aligned': True},
             'geometry': {'type': 'LineString', 'coordinates': coords}}
            for i, coords in enumerate(([[0, 0], [100, 0]], [[100, 0], [200, 0]]))
        ]}
        sketch = {'type': 'FeatureCollection', 'features': [{
            'type': 'Feature', 'properties': {'id': 0, 'sid': 'S0'},
            'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [200, 0]]},
        }]}
        alignment = {'1': {
            'BaseAlign': {'0': [0, 1]}, 'SketchAlign': {'0': ['S0']},
            'genType': 'OmissionMerge', 'degreeOfGeneralization': 1,
        }, 'checkAlignnum': 2}
        result = self.generalize(base, sketch, alignment)
        merged = [feat for feat in result['features']
                  if feat['properties'].get('genType') == 'OmissionMerge']
        self.assertEqual(len(merged), 1)
        self.assertEqual(shape(merged[0]['geometry']).length, 200)
