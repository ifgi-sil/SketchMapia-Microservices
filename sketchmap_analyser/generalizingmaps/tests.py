import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase


class UICompatibilityTests(SimpleTestCase):
    def test_pages_render(self):
        for path in ('/', '/documentation/', '/generalizingmaps/',
                     '/generalizingmaps/compare/', '/accounts/signup/',
                     '/useraccount/login/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_compare_csv_uploads_skip_malformed_rows(self):
        # Ten maps are expected by the comparison UI. Researcher 3 disagrees
        # with the other two, so every returned map has a difference.
        uploads = {}
        for researcher in range(1, 4):
            kind = 'Collapse' if researcher == 3 else 'No generalization'
            rows = ['Sketch Map,BaseId,Generalization Type']
            rows.extend(f'map{i},1,{kind}' for i in range(10))
            rows.append('invalid,row,with,too,many,columns')
            uploads[f'uploadR{researcher}align'] = SimpleUploadedFile(
                f'r{researcher}.csv', '\n'.join(rows).encode(),
                content_type='text/csv',
            )
        response = self.client.post(
            '/generalizingmaps/compare/compareResults/', uploads,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        results = json.loads(response.content)
        self.assertEqual(len(results), 10)
        for result in results:
            table = json.loads(result)
            self.assertEqual(table['columns'], ['R1', 'R2', 'R3'])
            self.assertEqual(table['data'], [
                ['No generalization', 'No generalization', 'Collapse']
            ])

    def test_compare_preserves_blank_for_unaligned_feature(self):
        kinds = ['Amalgamation', 'Collapse', 'No generalization']
        for omitted in range(3):
            with self.subTest(researcher=f'R{omitted + 1}'):
                uploads = {}
                for researcher, kind in enumerate(kinds):
                    rows = ['Sketch Map,BaseId,Generalization Type']
                    for map_number in range(10):
                        if researcher != omitted:
                            rows.append(f'map{map_number},1,{kind}')
                        # Keep every map and researcher present, even when
                        # this researcher has not aligned base feature 1.
                        rows.append(f'map{map_number},2,{kind}')
                    uploads[f'uploadR{researcher + 1}align'] = SimpleUploadedFile(
                        f'r{researcher + 1}.csv', '\n'.join(rows).encode(),
                        content_type='text/csv',
                    )
                response = self.client.post(
                    '/generalizingmaps/compare/compareResults/', uploads,
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertEqual(response.status_code, 200)
                results = json.loads(response.content)
                self.assertEqual(len(results), 10)
                expected = kinds.copy()
                expected[omitted] = None
                for result in results:
                    table = json.loads(result)
                    self.assertEqual(table['columns'], ['R1', 'R2', 'R3'])
                    self.assertEqual(table['index'], ['1', '2'])
                    self.assertEqual(table['data'], [expected, kinds])
