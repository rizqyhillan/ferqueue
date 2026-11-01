import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from ferqueue_cv.cleanup import apply_cleanup, audit_dataset, clean_dataset, write_report
from ferqueue_cv.dataset import collect_dataset


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.dataset = self.root / 'data/raw/vehicles'
        self.dataset.mkdir(parents=True)
        (self.dataset / 'classes.txt').write_text('mobil\ntruk\n', encoding='utf-8')
        self.config = {'dataset_dir': 'data/raw/vehicles', 'prepared_dir': 'data/processed/v1',
                       'run_dir': 'models/run1'}

    def image(self, name, color='red', label='0 .5 .5 .5 .5\n'):
        path = self.dataset / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (40, 30), color=color).save(path)
        if label is not None:
            path.with_suffix('.txt').write_text(label, encoding='utf-8')
        return path

    def candidate_names(self, plan):
        return {Path(item['path']).relative_to(self.config['dataset_dir']).as_posix()
                for item in plan['candidates']}

    def run_cleanup(self, answer='n', dry_run=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            run = clean_dataset(self.config, self.root, dry_run, lambda prompt: answer)
        return run, output.getvalue()

    def test_audit_lists_all_candidates_keeps_real_pairs_and_ignores_label_only_duplicates(self):
        self.image('a.png')
        self.image('renamed.png')
        self.image('different.png', color='blue')  # Same annotation is legitimate.
        self.image('unlabelled.png', color='green', label=None)
        (self.dataset / 'orphan.txt').write_text('0 .5 .5 .5 .5\n')
        plan = audit_dataset(self.config, self.root)
        self.assertEqual(self.candidate_names(plan), {'renamed.png', 'renamed.txt', 'unlabelled.png', 'orphan.txt'})
        self.assertEqual(len(plan['duplicates']), 1)
        self.assertTrue((self.dataset / 'renamed.png').exists())
        self.assertNotIn('classes.txt', self.candidate_names(plan))

    def test_only_explicit_lowercase_y_applies_and_quarantine_contains_original_files(self):
        self.image('a.png')
        extra = self.image('b.png')
        original = extra.read_bytes()
        for answer in ('', 'n', 'yes', 'Y'):
            run, _ = self.run_cleanup(answer)
            self.assertTrue(extra.exists())
            self.assertFalse((run / 'applied.json').exists())
            self.assertTrue((run / 'report.txt').exists())
        run, _ = self.run_cleanup('y')
        self.assertFalse(extra.exists())
        self.assertFalse(extra.with_suffix('.txt').exists())
        self.assertEqual((run / 'files/data/raw/vehicles/b.png').read_bytes(), original)
        self.assertTrue((self.dataset / 'a.png').exists())
        self.assertEqual(json.loads((run / 'applied.json').read_text())['status'], 'complete')
        _, rows = collect_dataset(self.dataset, self.root)
        self.assertEqual(len(rows), 1)

    def test_dry_run_does_not_prompt_even_if_callback_would_approve(self):
        extra = self.image('missing.png', label=None)
        def forbidden(prompt):
            self.fail('dry-run must not ask for approval')
        with contextlib.redirect_stdout(io.StringIO()):
            clean_dataset(self.config, self.root, dry_run=True, confirm=forbidden)
        self.assertTrue(extra.exists())

    def test_conflicting_annotations_and_shared_label_are_retained_for_manual_review(self):
        self.image('a.png')
        self.image('b.png', label='1 .5 .5 .5 .5\n')
        self.image('shared.png', color='green')
        self.image('shared.jpg', color='blue')
        plan = audit_dataset(self.config, self.root)
        self.assertEqual(plan['candidates'], [])
        self.assertTrue(any('anotasi berbeda' in issue for issue in plan['issues']))
        self.assertTrue(any('Label dipakai' in issue for issue in plan['issues']))

    def test_empty_background_labels_are_valid_and_duplicate_whitespace_is_ignored(self):
        self.image('background.png', color='blue', label='')
        self.image('background-copy.png', color='blue', label='\n')
        self.image('object.png', label='0 .5 .5 .5 .5\n1 .5 .5 .2 .2\n')
        self.image('object-copy.png', label='1 0.5 0.5 0.2 0.2\n0 0.5 0.5 0.5 0.5\n')
        plan = audit_dataset(self.config, self.root)
        self.assertEqual(len(plan['candidates']), 4)
        self.assertEqual(plan['issues'], [])

    def test_missing_labels_do_not_discard_the_annotated_duplicate(self):
        self.image('a-unlabelled.png', label=None)
        self.image('b-labelled.png')
        self.image('c-labelled.png')
        plan = audit_dataset(self.config, self.root)
        self.assertEqual(self.candidate_names(plan), {'a-unlabelled.png', 'c-labelled.png', 'c-labelled.txt'})
        self.assertTrue(plan['duplicates'][0]['keep'][0].endswith('b-labelled.png'))

    def test_unlabelled_duplicates_are_all_review_candidates_without_inventing_labels(self):
        self.image('a.png', label=None)
        self.image('b.png', label=None)
        plan = audit_dataset(self.config, self.root)
        self.assertEqual(self.candidate_names(plan), {'a.png', 'b.png'})
        self.assertEqual(plan['duplicates'][0]['keep'], [])
        self.assertFalse((self.dataset / 'a.txt').exists())

    def test_partial_move_failure_keeps_backups_and_records_completed_moves(self):
        self.image('a.png')
        extra = self.image('b.png')
        plan = audit_dataset(self.config, self.root)
        run = write_report(plan, self.root)
        rename = Path.rename

        def fail_second(source, target):
            if source.name == 'b.txt':
                raise OSError('simulated move failure')
            return rename(source, target)

        with patch.object(Path, 'rename', fail_second):
            with self.assertRaisesRegex(OSError, 'simulated'):
                apply_cleanup(plan, self.config, self.root, run)
        journal = json.loads((run / 'applied.json').read_text())
        self.assertTrue(journal['status'].startswith('incomplete'))
        self.assertEqual(len(journal['moved']), 1)
        self.assertFalse(extra.exists())
        self.assertTrue((self.root / journal['moved'][0]['backup']).exists())
        self.assertEqual(len((run / 'moves.jsonl').read_text().splitlines()), 1)
        self.assertTrue(extra.with_suffix('.txt').exists())
        self.assertTrue((self.dataset / 'a.png').exists())

    def test_separate_layout_and_groups_csv_are_updated_with_original_backup(self):
        for name in ('a', 'b'):
            image = self.image(f'images/session/{name}.png')
            label = self.dataset / f'labels/session/{name}.txt'
            label.parent.mkdir(parents=True, exist_ok=True)
            image.with_suffix('.txt').rename(label)
        groups = self.dataset / 'groups.csv'
        original = b'image,group,note\nsession/a.png,video1,keep\nsession/b.png,video1,remove\n'
        groups.write_bytes(original)
        run, _ = self.run_cleanup('y')
        self.assertTrue((self.dataset / 'labels/session/a.txt').exists())
        self.assertFalse((self.dataset / 'labels/session/b.txt').exists())
        self.assertEqual((run / 'original/data/raw/vehicles/groups.csv').read_bytes(), original)
        with groups.open(newline='') as handle:
            self.assertEqual(list(csv.DictReader(handle)), [{'image': 'session/a.png', 'group': 'video1', 'note': 'keep'}])
        collect_dataset(self.dataset, self.root)

    def test_changed_retained_image_or_label_or_new_file_cancels_entire_plan(self):
        first = self.image('a.png')
        extra = self.image('b.png')
        for target in (first, first.with_suffix('.txt')):
            plan = audit_dataset(self.config, self.root)
            run = write_report(plan, self.root)
            original = target.read_bytes()
            target.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, 'berubah sejak audit'):
                apply_cleanup(plan, self.config, self.root, run)
            self.assertTrue(extra.exists())
            target.write_bytes(original)
        plan = audit_dataset(self.config, self.root)
        run = write_report(plan, self.root)
        self.image('new.png', color='green')
        with self.assertRaisesRegex(ValueError, 'berubah sejak audit'):
            apply_cleanup(plan, self.config, self.root, run)
        self.assertTrue(extra.exists())

    def test_invalid_annotation_and_class_mapping_conflicts_do_not_get_deduplicated(self):
        self.image('a.png')
        self.image('session/b.png', label='bad-label\n')
        plan = audit_dataset(self.config, self.root)
        self.assertEqual(plan['candidates'], [])
        self.assertTrue(plan['issues'])
        (self.dataset / 'session/classes.txt').write_text('truk\nmobil\n')
        plan = audit_dataset(self.config, self.root)
        self.assertEqual(plan['candidates'], [])
        self.assertTrue(any('Urutan kelas berbeda' in issue for issue in plan['issues']))

    def test_prepared_dataset_and_malformed_groups_block_changes(self):
        missing = self.image('missing.png', label=None)
        output = self.root / self.config['prepared_dir']
        output.mkdir(parents=True)
        (output / 'manifest.json').write_text('{}')
        _, text = self.run_cleanup('y')
        self.assertIn('Cleanup diblokir', text)
        self.assertTrue(missing.exists())
        (output / 'manifest.json').unlink()
        (self.dataset / 'groups.csv').write_text('wrong,column\na,b\n')
        _, text = self.run_cleanup('y')
        self.assertIn('Cleanup diblokir', text)
        self.assertTrue(missing.exists())

    def test_path_escape_and_linked_files_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'di luar folder'):
            audit_dataset({**self.config, 'dataset_dir': '../outside'}, self.root)
        with self.assertRaisesRegex(ValueError, 'bukan root repo'):
            audit_dataset({**self.config, 'dataset_dir': '.'}, self.root)
        image = self.image('real.png')
        link = self.dataset / 'linked.png'
        try:
            link.symlink_to(image)
        except OSError:
            self.skipTest('Symlink tidak tersedia pada environment ini.')
        with self.assertRaisesRegex(ValueError, 'Symlink/junction'):
            audit_dataset(self.config, self.root)


if __name__ == '__main__':
    unittest.main()
