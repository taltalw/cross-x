"""LLM5 的只读输入适配、匿名化、原子来源定位及输出工具。"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / 'pipielines_v4/outputs/4_generate_fusion_question/computer_science/test_domain_count_3.jsonl'
DEFAULT_ATOMIC = ROOT / 'atomic'


def digest(value):
    """生成规范 JSON 的内容摘要。"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    """按块计算来源文件摘要。"""
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read_jsonl(path):
    """逐物理行读取对象，保持 U+2028 等内容不被拆行。"""
    with Path(path).open(encoding='utf-8') as stream:
        for line, text in enumerate(stream, 1):
            if text.strip():
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise ValueError(f'{path}:{line}: JSONL 行必须是对象')
                yield line, value


def write_json(path, value):
    """写 UTF-8 JSON。"""
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + '\n', encoding='utf-8')


def write_jsonl(path, rows):
    """写 UTF-8 JSONL。"""
    with Path(path).open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def fresh_dir(path):
    """新建空目录，拒绝覆盖已有产物。"""
    path = Path(path)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError('输出目录非空，请指定新的目录')
    path.mkdir(parents=True, exist_ok=True)
    return path


def qa(value):
    """提取可追溯原子问答的最小白名单。"""
    if not isinstance(value, dict):
        raise ValueError('原子材料需要 prompt/completion 对象')
    result = {key: value.get(key) for key in ('prompt', 'completion')}
    if any(not isinstance(v, str) or not v.strip() for v in result.values()):
        raise ValueError('原子材料 prompt/completion 必须非空')
    return result


class AtomicResolver:
    """仅索引当前样本需要的领域，并匹配原文问答摘要。"""

    def __init__(self, root):
        """保存原子目录，不读取无关文件。"""
        self.root = Path(root)
        self.index = {}

    def locate(self, domain, material):
        """返回精确匹配的本地来源或未解决状态，不猜测权威文献。"""
        if domain not in self.index:
            index = {}
            for path in sorted((self.root / domain).glob('*.jsonl')):
                sha = file_hash(path)
                for line, value in read_jsonl(path):
                    if all(isinstance(value.get(k), str) for k in ('prompt', 'completion')):
                        key = digest({k: value[k] for k in ('prompt', 'completion')})
                        index.setdefault(key, {'path': str(path.resolve()), 'line': line,
                                               'file_sha256': sha, 'content_sha256': key})
            self.index[domain] = index
        found = self.index[domain].get(digest(material))
        return ({'status': 'verified_local_atomic', **found} if found else
                {'status': 'embedded_only_atomic_unresolved', 'content_sha256': digest(material)})


def normalize(row, path, line, resolver, *, input_sha256=None):
    """适配真实阶段4，正式输入固定为原始题目与选项。

    Args:
        row: 单条阶段4输出。
        path: 来源 JSONL。
        line: 物理行号。
        resolver: 原子来源精确匹配器。
        input_sha256: 批量读取时复用同一文件摘要；省略时现场计算。
    """
    question, options, answer = (row.get(k) for k in ('question', 'options', 'answer'))
    if not isinstance(question, str) or not question.strip():
        raise ValueError('缺少非空 question')
    if not isinstance(options, dict) or len(options) < 2 or any(
            not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
            for k, v in options.items()):
        raise ValueError('options 必须是非空标签到选项文本的对象')
    if not isinstance(answer, str) or answer not in options:
        raise ValueError('answer 必须为单选标签')
    source, added = row.get('source_domain'), row.get('fusion_domains')
    if not isinstance(source, str) or not source or not isinstance(added, list):
        raise ValueError('缺少 source_domain/fusion_domains')
    domains = [source, *added]
    if any(not isinstance(d, str) or not d or '/' in d or d in ('.', '..') for d in domains):
        raise ValueError('领域标签非法')
    if len(set(domains)) != len(domains) or len(domains) not in (2, 3, 4) or row.get('domain_count') != len(domains):
        raise ValueError('重复领域或领域数不一致')
    used = row.get('used_samples', {})
    if not isinstance(used, dict) or set(used) - set(added):
        raise ValueError('used_samples 含未知领域或结构非法')
    sid = digest({'path': str(path.resolve()), 'line': line, 'row': row})[:24]
    sources, provenance, missing = [], [], []
    for domain in domains:
        materials = [row.get('sample')] if domain == source else used.get(domain, [])
        if not isinstance(materials, list):
            raise ValueError('used_samples 领域材料需为列表')
        if not materials or materials == [None]:
            missing.append(domain)
            continue
        for material in materials:
            material = qa(material)
            ref = resolver.locate(domain, material)
            source_id = f'src{len(sources) + 1}'
            content = f"Reference question:\n{material['prompt']}\nRecorded reference answer:\n{material['completion']}"
            sources.append({'source_id': source_id, 'domain': domain, 'content': content,
                            'provenance_status': ref['status']})
            provenance.append({'source_id': source_id, **ref})
    sample = {
        'sample_id': sid,
        'visible': {'sample_id': sid, 'question': question, 'options': options, 'visible_inputs': []},
        'review_bundle': {'declared_domains': domains, 'reference_answer': answer,
                          'reference_explanation': row.get('explanation'),
                          'grading_rule': {'type': 'single_choice_exact_label', 'origin': 'protocol_defined',
                                           'rule': 'Exactly one option should be correct. A response earns credit only if its selected label matches the reference answer; independently verify the gold label and uniqueness.'},
                          'sources': sources},
        'metadata': {'source_domain': source, 'k': len(domains), 'difficulty': row.get('difficulty', 'unknown'),
                     'generator_model_alias': row.get('model'), 'generator_family': 'unknown',
                     'input_file': str(path.resolve()), 'input_line': line,
                     'input_sha256': input_sha256 if input_sha256 is not None else file_hash(path),
                     'material_selection': 'source_sample+used_samples', 'missing_material_domains': missing,
                     'provenance': provenance, 'visibility': 'question_options_only'},
    }
    sample['content_sha256'] = digest(sample)
    return sample


def prepare(input_path=DEFAULT_INPUT, line=1, atomic_root=DEFAULT_ATOMIC):
    """选择单个物理行样本；不进行模型调用或文件写入。"""
    if type(line) is not int or line < 1:
        raise ValueError('line 必须为正整数')
    path = Path(input_path)
    for row_no, row in read_jsonl(path):
        if row_no == line:
            return normalize(row, path, line, AtomicResolver(atomic_root))
    raise ValueError('指定物理行不存在或为空')
