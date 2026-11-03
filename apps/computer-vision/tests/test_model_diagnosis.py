import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[3] / 'scripts/diagnose_model.py'
spec = importlib.util.spec_from_file_location('diagnose_model', path)
diagnosis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnosis)


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'Tes pembandingan bobot memerlukan NumPy.')
class DiagnosisTests(unittest.TestCase):
    def reader(self, values):
        import numpy as np
        class Reader:
            def get_variable_to_shape_map(self):
                return {key: np.asarray(value).shape for key, value in values.items()}
            def get_tensor(self, key):
                return np.asarray(values[key])
        return Reader()

    def test_model_weights_match_despite_optimizer_and_counter_extras(self):
        training = self.reader({'model/weight': [1., 2.], 'optimizer/slot': [5.], 'step/.ATTRIBUTES/VARIABLE_VALUE': 3000})
        exported = self.reader({'model/weight': [1., 2.], 'save_counter': 1})
        self.assertTrue(diagnosis.compare_weights(training, exported)['all_model_weights_identical'])
        self.assertEqual(diagnosis.global_step(training), 3000)

    def test_missing_or_different_model_weights_are_reported(self):
        training = self.reader({'model/weight': [1., 2.], 'model/bias': [1.]})
        exported = self.reader({'model/weight': [1., 3.]})
        report = diagnosis.compare_weights(training, exported)
        self.assertFalse(report['all_model_weights_identical'])
        self.assertEqual(report['missing_from_export'], ['model/bias'])
        self.assertEqual(report['different_variable_count'], 1)
        self.assertEqual(report['different_variables'][0]['max_abs_difference'], 1)

    def test_non_finite_and_empty_checkpoints_are_not_reported_as_valid(self):
        reader = self.reader({'model/weight': [float('nan')]})
        report = diagnosis.compare_weights(reader, reader)
        self.assertFalse(report['all_model_weights_identical'])
        self.assertEqual(report['non_finite_training'], ['model/weight'])
        self.assertFalse(diagnosis.compare_weights(self.reader({}), self.reader({}))['all_model_weights_identical'])

    def test_prediction_summary_respects_count_and_class_mapping(self):
        import numpy as np
        prediction = {'num_detections': np.array([2]),
                      'detection_scores': np.array([[.8, .2, .99]]),
                      'detection_classes': np.array([[3, 1, 2]]),
                      'detection_boxes': np.zeros((1, 3, 4))}
        report = diagnosis.summarize_predictions(prediction, ['Mobil', 'Truk', 'Bus'])
        self.assertEqual(report['top_5'][0]['class_name'], 'Bus')
        self.assertEqual(report['maximum_score_per_returned_class']['Truk'], None)
        self.assertEqual(report['counts_at_threshold']['0.5'], 1)


if __name__ == '__main__':
    unittest.main()
