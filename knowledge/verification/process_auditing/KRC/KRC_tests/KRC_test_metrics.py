"""KRC离线指标的独立合成数据与命令行回归测试。"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import KRC_core as core
import KRC_data as data
import KRC_evaluate as cli

DOMAINS = ['a', 'b', 'c', 'd']


def hit(index=1, method='embedding', score=0.6, rank=1):
    """创建单条可独立修改的原始检索命中。"""
    return {'query_index': index, 'method': method, 'score': score, 'rank': rank}


def candidate(cid='x', hits=None):
    """创建包含材料原文和RRF排序分数的候选。"""
    return {'candidate_id': cid, 'sample': {'prompt': cid, 'completion': 'evidence'},
            'rrf_score': 0.1, 'hits': hits if hits is not None else [hit(), hit(method='bm25', score=5)]}


def raw(atom='one', source='a', k=2):
    """创建合法阶段3方案，保证同一原子样本跨k身份一致。"""
    added = [d for d in DOMAINS if d != source][:k - 1]
    return {'source_domain': source, 'domain_count': k, 'fusion_domains': added,
            'sample': {'prompt': atom, 'completion': 'answer'}, 'question_plan': 'plan',
            'required_key_facts': {d: [{'key_fact': 'fact', 'necessity': 'essential'}] for d in added},
            'retrieved_samples': {d: [candidate()] for d in added},
            'retrieval': {'method': 'hybrid', 'embedding_config_hash': 'fixed',
                          'embedding_model': 'local', 'rrf_k': 60, 'top_k_per_query_method': 10,
                          'candidate_limit': 10, 'bm25_k1': 1.5, 'bm25_b': 0.75}}


def normalized(row=None):
    """为单元测试调用正式输入校验器。"""
    return data.normalize_record(row if row is not None else raw(), DOMAINS)


def normalization():
    """提供固定领域范围，避免每需求Min-Max的恒一退化。"""
    return {'ranges': {d: {'min': 0, 'max': 10} for d in DOMAINS}}


def evaluate(rows, budgets=None, thresholds=None):
    """从原始方案运行指标计算并返回中间表与汇总。"""
    plans = [normalized(r) for r in rows]
    budgets = budgets or ['all']
    pairs = core.extract_pairs(plans, normalization())
    needs = core.requirement_scores(plans, pairs, budgets)
    stats = core.aggregate(needs, DOMAINS, sorted({p['domain_count'] for p in plans}),
                           budgets, thresholds or [0.5])
    return pairs, needs, stats


def need_for(needs, mode='hybrid_complete', budget='all', index=1):
    """选择某个模式和预算下的第一项需求。"""
    return next(r for r in needs if r['mode'] == mode and r['budget'] == budget and r['query_index'] == index)


class ScoreTests(unittest.TestCase):
    """检验配对筛选、缺失语义以及融合计算顺序。"""

    def test_missing_embedding_excludes_bm25_and_rrf(self):
        row = raw()
        row['retrieved_samples']['b'] = [candidate(hits=[hit(method='bm25', score=10)])]
        pairs, needs, stats = evaluate([row])
        self.assertFalse(pairs[0]['embedding_available'])
        self.assertIsNone(pairs[0]['bm25_norm'])
        for r in needs:
            self.assertIsNone(r['weight'])
        self.assertTrue(all(r['covered'] is None for r in stats['requirement_coverage']))

    def test_missing_bm25_does_not_fill_or_reweight(self):
        row = raw()
        row['retrieved_samples']['b'] = [candidate(hits=[hit(score=0.8)])]
        _, needs, _ = evaluate([row])
        self.assertEqual(need_for(needs, 'cosine_observed')['weight'], 0.8)
        for mode in core.MODES[1:]:
            self.assertIsNone(need_for(needs, mode)['weight'])

    def test_zero_and_negative_cosine_remain_eligible(self):
        for score in (0, -0.8):
            with self.subTest(score=score):
                row = raw()
                row['retrieved_samples']['b'][0]['hits'][0]['score'] = score
                pairs, needs, _ = evaluate([row])
                self.assertTrue(pairs[0]['both_available'])
                self.assertEqual(pairs[0]['cosine_norm'], 0)
                self.assertEqual(need_for(needs)['weight'], 0.25)

    def test_same_candidate_fuse_before_max(self):
        row = raw()
        row['retrieved_samples']['b'] = [
            candidate('x', [hit(score=0.1), hit(method='bm25', score=10)]),
            candidate('y', [hit(score=0.9), hit(method='bm25', score=0)])]
        _, needs, _ = evaluate([row])
        self.assertAlmostEqual(need_for(needs)['weight'], 0.55)
        self.assertEqual(need_for(needs)['best_candidate_id'], 'x')

    def test_conditional_denominator_counts_needs_not_pairs(self):
        row = raw()
        row['required_key_facts']['b'] *= 3
        row['retrieved_samples']['b'] = [candidate('x', [hit(1, score=0.9), hit(2, score=0.1)]),
                                          candidate('y', [hit(1, score=0.8)])]
        _, needs, stats = evaluate([row])
        group = next(r for r in stats['per_domain'] if r['mode'] == 'cosine_observed')
        self.assertEqual(group['evaluated_requirements'], 2)
        self.assertEqual(group['excluded_requirements'], 1)
        self.assertEqual(group['eligible_pairs'], 3)
        self.assertEqual(group['binary'], 0.5)
        self.assertEqual(group['weighted'], 0.5)
        self.assertIsNone(need_for(needs, 'cosine_observed', index=3)['weight'])

    def test_complete_modes_share_support_set(self):
        row = raw()
        row['retrieved_samples']['b'].append(candidate('y', [hit(score=0.99)]))
        _, needs, _ = evaluate([row])
        self.assertEqual(need_for(needs, 'cosine_observed')['eligible_pairs'], 2)
        self.assertEqual(need_for(needs, 'cosine_complete')['weight'], 0.6)
        self.assertEqual({need_for(needs, m)['eligible_pairs'] for m in core.MODES[1:]}, {1})

    def test_boundary_has_no_rounding(self):
        for score, expected in [(0.7, 1), (0.69999999999, 0)]:
            row = raw()
            row['retrieved_samples']['b'][0]['hits'][0]['score'] = score
            _, _, stats = evaluate([row], thresholds=[0.7])
            result = next(r for r in stats['requirement_coverage'] if r['mode'] == 'cosine_observed')
            self.assertEqual(result['covered'], expected)

    def test_empty_candidates_excluded(self):
        row = raw()
        row['retrieved_samples']['b'] = []
        _, needs, stats = evaluate([row])
        self.assertTrue(all(r['weight'] is None for r in needs))
        self.assertTrue(all(r['evaluated_plans'] == 0 for r in stats['summary']))

    def test_budget_fixed_need_max_monotone_but_conditional_rate_not(self):
        row = raw()
        row['required_key_facts']['b'] *= 2
        row['retrieved_samples']['b'] = [candidate('x', [hit(1, score=0.8)]),
                                          candidate('y', [hit(1, score=0.9), hit(2, score=0.1)])]
        _, needs, stats = evaluate([row], budgets=['1', '2'])
        self.assertLessEqual(need_for(needs, 'cosine_observed', '1')['weight'],
                             need_for(needs, 'cosine_observed', '2')['weight'])
        groups = {r['budget']: r for r in stats['per_plan'] if r['mode'] == 'cosine_observed'}
        self.assertEqual(groups['1']['binary'], 1)
        self.assertEqual(groups['2']['binary'], 0.5)

    def test_domain_means_are_equal_weighted(self):
        row = raw(k=3)
        row['required_key_facts']['c'] *= 3
        row['retrieved_samples']['b'] = [candidate(hits=[hit(score=1)])]
        row['retrieved_samples']['c'] = [candidate(hits=[hit(j, score=0) for j in (1, 2, 3)])]
        _, _, stats = evaluate([row])
        group = next(r for r in stats['per_plan'] if r['mode'] == 'cosine_observed')
        self.assertEqual(group['weighted'], 0.5)
        self.assertEqual(group['binary'], 0.5)

    def test_source_macro_ignores_source_sample_count_and_marks_missing(self):
        rows = [raw('one', 'a'), raw('two', 'a'), raw('one', 'b')]
        for row in rows:
            target = row['fusion_domains'][0]
            row['retrieved_samples'][target] = [candidate(hits=[hit(score=1 if row['source_domain'] == 'a' else 0)])]
        _, _, stats = evaluate(rows)
        group = next(r for r in stats['summary'] if r['mode'] == 'cosine_observed')
        self.assertEqual(group['observed_source_weighted'], 0.5)
        self.assertIsNone(group['macro_weighted'])
        self.assertEqual(group['missing_sources'], ['c', 'd'])

    def test_invalid_alpha_and_threshold(self):
        for alpha in (True, -0.1, 1.1, float('nan')):
            with self.assertRaises(ValueError):
                core.extract_pairs([normalized()], normalization(), alpha)
        for threshold in (0, -0.1, True, float('nan'), 1.1):
            with self.assertRaises(ValueError):
                evaluate([raw()], thresholds=[threshold])


class DataTests(unittest.TestCase):
    """验证固定参考范围、输入数据约束及跨k划分。"""

    def test_fixed_minmax_clips_and_does_not_rescale_per_need(self):
        norm = normalization()
        for raw_score, expected, clipped in [(2, 0.2, 'none'), (-1, 0, 'low'), (12, 1, 'high')]:
            self.assertEqual(data.normalize_bm25(raw_score, 'b', norm), (expected, clipped))

    def test_reference_degenerate_and_missing_domain_fail(self):
        with self.assertRaises(ValueError):
            data.fit_normalization([normalized()])
        with self.assertRaises(ValueError):
            data.normalize_bm25(1, 'unknown', normalization())

    def test_fit_reference_keeps_bm25_only_hits(self):
        row = raw()
        row['retrieved_samples']['b'].append(candidate('y', [hit(method='bm25', score=15)]))
        norm = data.fit_normalization([normalized(row)])
        self.assertEqual(norm['ranges']['b'], {'min': 5, 'max': 15, 'observed_scores': 2})

    def test_input_score_index_rank_validation(self):
        for field, bad in [('score', True), ('score', float('nan')), ('score', 1.01),
                           ('score', -1.01), ('rank', 0), ('rank', True), ('query_index', 0),
                           ('query_index', 2), ('query_index', True)]:
            with self.subTest(field=field, bad=bad):
                row = raw()
                row['retrieved_samples']['b'][0]['hits'][0][field] = bad
                with self.assertRaises(ValueError):
                    normalized(row)
        row = raw()
        row['retrieved_samples']['b'][0]['hits'][1]['score'] = -1
        with self.assertRaises(ValueError):
            normalized(row)

    def test_duplicate_hits_deduplicate_or_reject_conflict(self):
        row = raw()
        hits = row['retrieved_samples']['b'][0]['hits']
        hits.append(copy.deepcopy(hits[0]))
        self.assertEqual(len(normalized(row)['candidates']['b'][0]['hits']), 2)
        hits[-1]['rank'] = 2
        with self.assertRaises(ValueError):
            normalized(row)

    def test_duplicate_candidate_fails(self):
        row = raw()
        row['retrieved_samples']['b'] *= 2
        with self.assertRaises(ValueError):
            normalized(row)

    def test_unicode_separator_bom_and_crlf_preserve_physical_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.jsonl'
            rows = [raw('line\u2028separator'), raw('next')]
            path.write_bytes(('\ufeff' + '\r\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\r\n').encode())
            plans, meta = data.read_plans(path, DOMAINS, [2])
            self.assertEqual([p['input_line'] for p in plans], [1, 2])
            self.assertEqual(plans[0]['sample']['prompt'], 'line\u2028separator')
            self.assertEqual(meta['rows_read'], 2)

    def test_mixed_bm25_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.jsonl'
            rows = [raw('one'), raw('two')]
            rows[1]['retrieval']['bm25_k1'] = 2.0
            path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
            with self.assertRaises(ValueError):
                data.read_plans(path, DOMAINS, [2])

    def test_mixed_embedding_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.jsonl'
            rows = [raw('one'), raw('two')]
            rows[1]['retrieval']['embedding_config_hash'] = 'other'
            path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
            with self.assertRaises(ValueError):
                data.read_plans(path, DOMAINS, [2])

    def test_split_is_paired_disjoint_and_order_invariant(self):
        plans = [normalized(raw(str(i), source, k)) for source in ('a', 'b') for i in range(10) for k in (2, 3)]
        ref, sample, pool, meta = data.split_plans(plans, [2, 3])
        reverse = data.split_plans(list(reversed(plans)), [2, 3])
        self.assertEqual(meta, reverse[3])
        self.assertEqual([p['plan_id'] for p in sample], [p['plan_id'] for p in reverse[1]])
        identity = lambda ps: {(p['source_domain'], p['atomic_id']) for p in ps}
        self.assertFalse(identity(ref) & identity(pool))
        self.assertLessEqual(identity(sample), identity(pool))
        for subset in (ref, sample, pool):
            for source, atom in identity(subset):
                self.assertEqual({p['domain_count'] for p in subset if p['source_domain'] == source and p['atomic_id'] == atom}, {2, 3})

    def test_pinned_samples_retained_and_excluded_from_reference(self):
        plans = [normalized(raw(str(i), k=k)) for i in range(10) for k in (2, 3)]
        pinned = [p for p in plans if p['sample']['prompt'] == '3']
        ref, sample, _, _ = data.split_plans(plans, [2, 3], pinned=pinned)
        self.assertEqual({p['plan_id'] for p in sample}, {p['plan_id'] for p in pinned})
        self.assertFalse({p['atomic_id'] for p in sample} & {p['atomic_id'] for p in ref})
        with self.assertRaises(ValueError):
            data.split_plans(plans, [2, 3], pinned=pinned[:1])


class CliTests(unittest.TestCase):
    """仅用合成文件在python -S进程中验证完整交付与保护措施。"""

    def setUp(self):
        """准备每源五个原子样本和可拟合的BM25参考范围。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'input'
        self.source.mkdir()
        self.file = self.source / 'records.jsonl'
        rows = [raw(str(i), source) for source in ('a', 'b') for i in range(5)]
        for row in rows:
            domain = row['fusion_domains'][0]
            row['retrieved_samples'][domain] = [candidate('x', [hit(score=0.8), hit(method='bm25', score=0)]),
                                                 candidate('y', [hit(score=0.2), hit(method='bm25', score=10)])]
        self.file.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
        self.output = self.base / 'KRC_output'

    def run_cli(self, *extra, output=None):
        """禁用site-packages运行真实CLI，返回退出码和输出。"""
        args = [sys.executable, '-S', '-X', 'utf8', str(ROOT / 'KRC_evaluate.py'),
                '--input', str(self.source), '--output', str(output or self.output),
                '--domains', 'a', 'b', '--domain-counts', '2', '--thresholds', '0.5', '--budgets', '1', '2']
        return subprocess.run(args + list(extra), text=True, capture_output=True, timeout=30)

    def test_full_offline_cli_outputs_and_denominators(self):
        before = self.file.read_bytes()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p.name for p in self.output.iterdir()}, set(cli.FILES))
        self.assertTrue(all(p.name.startswith('KRC_') for p in self.output.iterdir()))
        report = json.loads((self.output / 'KRC_summary.json').read_text())
        self.assertEqual(report['manifest']['model_calls'], 0)
        self.assertEqual(report['diagnostics']['total_requirements'], 2)
        self.assertEqual(report['diagnostics']['embedding_pairs'], 4)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual({r['macro_weighted'] for r in report['summary'] if r['mode'] == 'hybrid_complete' and r['budget'] == 'all'}, {0.6})

    def test_existing_reports_require_overwrite(self):
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli('--overwrite').returncode, 0)

    def test_output_inside_input_rejected(self):
        result = self.run_cli(output=self.source / 'KRC_results')
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.source / 'KRC_results').exists())

    def test_output_symlink_rejected(self):
        self.output.mkdir()
        (self.output / 'KRC_summary.json').symlink_to(self.file)
        before = self.file.read_bytes()
        self.assertEqual(self.run_cli('--overwrite').returncode, 2)
        self.assertEqual(self.file.read_bytes(), before)

    def test_saved_normalization_reuse_and_tamper_rejection(self):
        self.assertEqual(self.run_cli().returncode, 0)
        norm = self.output / 'KRC_normalization.json'
        result = self.run_cli('--normalization', str(norm), output=self.base / 'KRC_reuse')
        self.assertEqual(result.returncode, 0, result.stderr)
        changed = json.loads(norm.read_text())
        changed['ranges']['b']['max'] = 11
        norm.write_text(json.dumps(changed), encoding='utf-8')
        self.assertEqual(self.run_cli('--normalization', str(norm), output=self.base / 'KRC_bad').returncode, 2)

    def test_saved_normalization_and_manifest_protected(self):
        self.assertEqual(self.run_cli().returncode, 0)
        for option, filename in [('--normalization', 'KRC_normalization.json'), ('--sample-manifest', 'KRC_run_manifest.json')]:
            before = (self.output / filename).read_bytes()
            result = self.run_cli(option, str(self.output / filename), '--overwrite')
            self.assertEqual(result.returncode, 2)
            self.assertEqual((self.output / filename).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
