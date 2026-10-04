"""Step-4-only pure validation, budgets, identity and presentation helpers."""
from copy import deepcopy
import hashlib
import json
import random
import re

from _pipeline_common import compact_text, validate_generation as shared_validate_generation

VERSION = 'v5-concise-1'
LABELS = 'ABCD'
CHECKS = ('single_target', 'self_contained', 'evidence_grounded',
          'no_knowledge_giveaway', 'same_answer_form', 'no_surface_shortcut')
ANSWER_FORMS = ('number', 'decision', 'short_text', 'expression', 'code')
BLUEPRINT_LIMITS = {'target': 20, 'dependency_summary': 70, 'domain_role': 35}


def default_budget(count):
    if type(count) is not int or not 2 <= count <= 7:
        raise ValueError('budget domain_count must be between 2 and 7')
    extra = count - 2
    result = dict(question_target_words=[30 + 10*extra, 55 + 15*extra],
                  question_max_words=75 + 20*extra, option_max_words=18 + 2*extra,
                  total_visible_max_words=130 + 30*extra)
    for stem in ('question', 'option', 'total_visible'):
        result[stem + '_max_chars'] = result[stem + '_max_words'] * 12
    result['status'] = 'engineering_default' if count <= 4 else 'uncalibrated_extension'
    return result


def validate_budget(value):
    expected = set(default_budget(2)) - {'status'}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f'length budget requires exactly {sorted(expected)}')
    target = value['question_target_words']
    if not isinstance(target, list) or len(target) != 2 or any(type(n) is not int or n < 0 for n in target):
        raise ValueError('question_target_words must be two nonnegative integers')
    for key in expected - {'question_target_words'}:
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError(f'{key} must be a nonnegative integer')
    if not target[0] <= target[1] <= value['question_max_words'] <= value['total_visible_max_words']:
        raise ValueError('invalid question/total word budget relationship')
    if value['option_max_words'] > value['total_visible_max_words'] or any(
            value[stem + '_max_chars'] < value[stem + '_max_words'] for stem in ('question', 'option', 'total_visible')):
        raise ValueError('invalid character or option budget relationship')
    if max(value['question_max_chars'], value['option_max_chars']) > value['total_visible_max_chars']:
        raise ValueError('total character budget must cover any single field')
    return deepcopy(value)


def load_budget_file(path):
    if path is None:
        return {}, dict(BLUEPRINT_LIMITS)
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not set(value) <= {'budgets', 'blueprint_limits'}:
        raise ValueError('budget file allows budgets and blueprint_limits')
    budgets = value.get('budgets', {})
    if not isinstance(budgets, dict) or any(k not in tuple(map(str, range(2, 8))) for k in budgets):
        raise ValueError('budgets must be keyed by domain counts 2 through 7')
    budgets = {int(k): validate_budget(v) for k, v in budgets.items()}
    limits = value.get('blueprint_limits', BLUEPRINT_LIMITS)
    if not isinstance(limits, dict) or set(limits) != set(BLUEPRINT_LIMITS) or any(type(n) is not int or n < 1 for n in limits.values()):
        raise ValueError('blueprint_limits requires three positive integer limits')
    return budgets, dict(limits)


def budget_for(count, overrides=None):
    result = default_budget(count)
    if overrides and count in overrides:
        result.update(validate_budget(overrides[count]))
        result['status'] = 'custom' if count <= 4 else 'uncalibrated_extension'
    return result


def validate_blueprint(value, domains, limits=None):
    limits = limits or BLUEPRINT_LIMITS
    fields = {'target', 'answer_form', 'dependency_summary', 'domain_roles'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('compact_blueprint requires target, answer_form, dependency_summary, domain_roles')
    if value['answer_form'] not in ANSWER_FORMS:
        raise ValueError('invalid compact_blueprint.answer_form')
    result = {'answer_form': value['answer_form']}
    for field in ('target', 'dependency_summary'):
        result[field] = compact_text(value[field], field)
        if len(result[field].split()) > limits[field] or len(result[field]) > limits[field]*12:
            raise ValueError(f'compact_blueprint.{field} exceeds configured budget')
    roles = value['domain_roles']
    if not isinstance(roles, dict) or set(roles) != set(domains):
        raise ValueError('domain_roles must cover exactly all participating domains including source')
    result['domain_roles'] = {}
    for domain in domains:
        role = roles[domain]
        if not isinstance(role, dict) or set(role) != {'knowledge', 'role', 'removal_effect'}:
            raise ValueError('domain role requires knowledge, role, removal_effect')
        result['domain_roles'][domain] = {}
        for field in role:
            text = compact_text(role[field], f'{domain}.{field}')
            if len(text.split()) > limits['domain_role'] or len(text) > limits['domain_role']*12:
                raise ValueError(f'domain_roles.{domain}.{field} exceeds configured budget')
            result['domain_roles'][domain][field] = text
    return result


def validate_generation(value, participating, available_samples, answer_form=None):
    # Shared whitespace/case normalization cannot compare code/expression outcomes:
    # indentation and identifier case may change their meaning. Check these locally
    # and delegate the remaining original schema to the unchanged shared validator.
    checked = value
    if answer_form in ('code', 'expression'):
        if not isinstance(value, dict) or not isinstance(value.get('options'), dict) or set(value['options']) != set(LABELS):
            raise ValueError('options must contain exactly A, B, C, and D')
        for label, text in value['options'].items():
            compact_text(text, f'option {label}')
        if len({text.strip() for text in value['options'].values()}) != 4:
            raise ValueError('options must be distinct')
        checked = {**value, 'options': {label: f'validated visible outcome {label}' for label in LABELS}}
    try:
        result = shared_validate_generation(checked, participating, available_samples)
    except (TypeError, KeyError, IndexError) as exc:
        raise ValueError(f'invalid generation schema: {exc}') from None
    entries = result['distractor_analysis']
    if len({e['option'] for e in entries}) != 3 or {e['option'] for e in entries} != set(LABELS) - {result['answer']}:
        raise ValueError('each wrong option must be annotated exactly once')
    result['question'] = value['question'].strip()
    result['options'] = {k: value['options'][k].strip() for k in LABELS}
    return result


def visible_item(row):
    """White list for evaluation and blind audits; never serialize the full record."""
    return {'question': row['question'], 'options': dict(row['options'])}


def length_stats(row):
    question = row['question']
    options = row['options']
    words = {k: len(options[k].split()) for k in LABELS}
    chars = {k: len(options[k]) for k in LABELS}
    return dict(question_words=len(question.split()), option_words=words,
                options_words=sum(words.values()), total_visible_words=len(question.split())+sum(words.values()),
                question_chars=len(question), option_chars=chars, options_chars=sum(chars.values()),
                total_visible_chars=len(question)+sum(chars.values()))


def hard_issues(row, budget):
    stats = length_stats(row)
    issues = []
    for unit in ('words', 'chars'):
        fields = [('question', stats['question_'+unit], budget['question_max_'+unit]),
                  ('total_visible', stats['total_visible_'+unit], budget['total_visible_max_'+unit])]
        fields += [(f'options.{k}', stats['option_'+unit][k], budget['option_max_'+unit]) for k in LABELS]
        for field, actual, limit in fields:
            if actual > limit:
                issues.append(dict(check='length', field=field, unit=unit, actual=actual, limit=limit))
    # Do not substitute letters globally: variables and code may use A/B/C/D.
    for field, text in [('explanation', row['explanation']), ('plan_adjustment', row['plan_adjustment'])] + [
            (f'distractor_analysis.{i}.reason', e['reason']) for i, e in enumerate(row['distractor_analysis'])]:
        if re.search(r'(?i:\b(?:options?|choices?|answers?))\s*[\(\[]?\s*[A-D]\b|\b[A-D]\s*[).:]\s|\b[A-D]\s+(?:is\s+(?:the\s+)?(?:correct|incorrect|right|wrong)|returns|omits|ignores|fails|computes|uses|gives)\b', text):
            issues.append(dict(check='unsafe_option_reference', field=field,
                               reason='Describe option content instead of a letter reference.'))
    return issues


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def plan_key(row):
    if row.get('plan_id') is not None:
        if not isinstance(row['plan_id'], str) or not row['plan_id'].strip():
            raise ValueError('plan_id must be a nonempty string')
        return row['plan_id']
    return digest({'sample': {k: row['sample'][k] for k in ('prompt', 'completion')},
                   'source_domain': row['source_domain'], 'fusion_domains': sorted(row['fusion_domains']),
                   'question_plan': row['question_plan'], 'answer_plans': row['answer_plans']})


def item_id(key, difficulty):
    return digest([VERSION, key, difficulty])


def shuffle_options(row, seed, identity):
    result = deepcopy(row)
    order = list(LABELS)
    random.Random(int(digest([seed, identity]), 16)).shuffle(order)
    mapping = dict(zip(LABELS, order))
    moved = {mapping[k]: row['options'][k] for k in LABELS}
    result['options'] = {k: moved[k] for k in LABELS}
    result['answer'] = mapping[row['answer']]
    for entry in result['distractor_analysis']:
        entry['option'] = mapping[entry['option']]
    return result, mapping


def audit_payload(row, source, sample, fusion_domains, selected):
    return {**visible_item(row), 'participating_domains': [source, *fusion_domains],
            'source_sample': sample, 'selected_samples': selected}


def json_object(value):
    if not isinstance(value, dict):
        raise ValueError('response must be a JSON object')
    return value


def validate_audit(value, domains):
    json_object(value)
    correct = value.get('correct_options')
    if not isinstance(correct, list) or any(not isinstance(k, str) or k not in tuple(LABELS) for k in correct) or len(set(correct)) != len(correct):
        raise ValueError('correct_options must be a distinct list of option labels (possibly empty)')
    checks = value.get('checks')
    if not isinstance(checks, dict) or set(checks) != set(CHECKS) or any(v not in ('pass','fail','uncertain') for v in checks.values()):
        raise ValueError('invalid audit checks')
    roles = value.get('domain_necessity')
    if not isinstance(roles, dict) or set(roles) != set(domains):
        raise ValueError('audit must cover every participating domain')
    for domain, role in roles.items():
        if not isinstance(role, dict) or set(role) != {'necessary', 'reason'} or type(role.get('necessary')) not in (bool, type(None)):
            raise ValueError('necessary must be true, false, or null')
        compact_text(role.get('reason'), f'{domain}.reason')
    issues = value.get('issues')
    if not isinstance(issues, list) or any(not isinstance(i, str) or not i.strip() for i in issues):
        raise ValueError('audit issues must be strings')
    compact_text(value.get('solution_summary'), 'solution_summary')
    return deepcopy(value)


def audit_issues(value, answer):
    issues = []
    if value['correct_options'] != [answer]:
        issues.append(dict(check='answer_conflict', proposed=answer, audited=value['correct_options']))
    issues += [dict(check=k, status=v) for k,v in value['checks'].items() if v != 'pass']
    issues += [dict(check='domain_necessity', domain=d, **r) for d,r in value['domain_necessity'].items() if r['necessary'] is not True]
    issues += [dict(check='semantic_issue', reason=i) for i in value['issues']]
    return issues
