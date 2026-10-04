"""Offline engineering checks; fixtures do not establish generated semantic quality."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from _concise_fusion import (
    CHECKS, audit_issues, audit_payload, budget_for, default_budget, digest,
    hard_issues, item_id, length_stats, load_budget_file, plan_key, shuffle_options,
    validate_audit, validate_blueprint, validate_budget, validate_generation, visible_item,
)
from knowledge.pipelines._knowledge_search_common import APIError, JSONAPI
import audit_step4_concise as stats_script

spec = importlib.util.spec_from_file_location('concise_stage4', ROOT/'4_generate_fusion_question.py')
s4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s4)


def blueprint():
    return dict(target='The area returned by the function', answer_form='code',
                dependency_summary='Geometry determines area and Python determines the returned expression.',
                domain_roles={d:dict(knowledge=k,role=r,removal_effect=e) for d,k,r,e in [
                    ('mathematics','Circle area','Determine the area expression','The area expression is wrong'),
                    ('computer_science','Function return semantics','Return the computed area','The returned value is wrong')]})


def input_row():
    answers = [dict(type=t,missing_domain='mathematics' if t=='missing_domain_knowledge' else None,plan='Concrete outcome '+str(i))
               for i,t in enumerate(('correct','missing_domain_knowledge','parallel_knowledge','incorrect_domain_relation'))]
    sample = dict(prompt='What does return do in Python?',completion='It returns a value from the function.')
    return dict(source_domain='mathematics',sample=dict(prompt='Find the area of a circle.',completion='pi times radius squared'),
                key_facts=['circle area','radius squared'],fusion_domains=['computer_science'],domain_count=2,
                question_plan='Complete the returned circle area expression.',answer_plans=answers,
                required_key_facts={'computer_science': [dict(key_fact=k,necessity='Needed to return area.')
                      for k in ('return statement','math pi','exponent operator')]},
                retrieved_samples={'computer_science':[{'sample':sample,'candidate_id':'fixture','hits':[]}]},
                retrieval={'method':'fixture','queries':['original query']})


def screen(row):
    return dict(feasible=True,reason='Both domains contribute.',
                selected_samples={d:[c['sample'] for c in cs] for d,cs in row['retrieved_samples'].items()},
                **{k:copy.deepcopy(row[k]) for k in ('question_plan','answer_plans','required_key_facts')},
                compact_blueprint=blueprint())


def candidate():
    row = input_row()
    return dict(question='With math imported and r > 0, which function returns the area of a circle of radius r?',
                options={'A':'def area(r):\n    return math.pi * r**2','B':'def area(r):\n    return r**2',
                         'C':'def area(r):\n    math.pi * r**2\n    return r','D':'def area(r):\n    return (math.pi * r)**2'},
                answer='A',explanation='Geometry requires pi times radius squared; Python must return that value.',
                distractor_analysis=[dict(option=k,type=t,missing_domain='mathematics' if k=='B' else None,reason=r)
                    for k,t,r in [('B','missing_domain_knowledge','Omitting pi underestimates the area by a factor of pi.'),
                                  ('C','parallel_knowledge','The area is computed but not propagated to return, so radius is returned.'),
                                  ('D','incorrect_domain_relation','The square includes pi, producing pi squared times radius squared.')]],
                used_samples=screen(row)['selected_samples'],plan_adjustment='')


def passing_audit(payload):
    answer_text = candidate()['options']['A']
    return dict(correct_options=[k for k,v in payload['options'].items() if v==answer_text],
                solution_summary='Verify the area expression and return semantics.',checks=dict.fromkeys(CHECKS,'pass'),
                domain_necessity={d:dict(necessary=True,reason='Required for this final result.') for d in payload['participating_domains']},issues=[])


class FakeAPI:
    model='mock-generation'
    def __init__(self, generate=None, judge=None, screening=None, fail_at=None):
        self.generate=generate or (lambda data, n: candidate())
        self.judge=judge or (lambda data,n: passing_audit(data))
        self.screening=screening
        self.fail_at=fail_at
        self.calls=[]
        self.generation_count=0
        self.audit_count=0
    def chat(self,prompt,data,validate,max_tokens):
        self.calls.append((prompt,copy.deepcopy(data)))
        if self.fail_at==len(self.calls): raise APIError('fixture retries exhausted')
        if prompt==s4.SCREEN_PROMPT:
            value=self.screening or screen(input_row())
        elif prompt==s4.AUDIT_PROMPT:
            self.audit_count+=1
            value=self.judge(data,self.audit_count)
        else:
            self.generation_count+=1
            value=self.generate(data,self.generation_count)
        return validate(copy.deepcopy(value))


class ConciseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'input.jsonl'
        self.output=self.root/'output.jsonl'
        self.audit=self.root/'output.audit.jsonl'
        self.source.write_text(json.dumps(input_row())+'\n')
    def process(self,api=None,**kwargs):
        return s4.process(self.source,self.output,api=api or FakeAPI(),domain_count=2,num=None,
                          max_tokens=4096,max_input_chars=160000,overwrite=False,**kwargs)
    def rows(self,path=None):
        return [json.loads(t) for t in (path or self.output).read_text().splitlines()]
    def validate_candidate(self,row=None):
        selected=screen(input_row())['selected_samples']
        refs={d:{(s['prompt'],s['completion']) for s in ss} for d,ss in selected.items()}
        return validate_generation(row or candidate(),['mathematics','computer_science'],refs, 'code')

    def test_original_step3_input_and_default_flow(self):
        api=FakeAPI()
        report=self.process(api)
        self.assertEqual((report['processed'],report['feasible_plans'],report['initial_candidates'],report['accepted']), (1,1,3,3))
        self.assertEqual(len(api.calls),7)
        self.assertEqual(report['logical_api_calls'],7)
        self.assertEqual(report['repair_candidates'],0)
        rows=self.rows()
        self.assertEqual([r['difficulty'] for r in rows],['easy','medium','hard'])
        original=input_row()
        for row in rows:
            for field in ('sample','key_facts','fusion_domains','domain_count','retrieval','question_plan','answer_plans','required_key_facts'):
                self.assertEqual(row[field],original[field])
            self.assertEqual(row['construction']['original_plan']['required_key_facts'],original['required_key_facts'])
            self.assertEqual(row['construction']['semantic_audit_status'],'passed')
            self.assertEqual(row['construction']['error_label_status'],'construction_intent')
            self.assertEqual(row['options'][row['answer']],candidate()['options']['A'])
        self.assertEqual(rows[-1]['construction']['duplicate_difficulties'],['easy','medium'])
        self.assertEqual(len({r['item_id'] for r in rows}),3)

    def test_blueprint_exact_domain_coverage_and_limits(self):
        for missing in ('mathematics','computer_science'):
            bad=blueprint(); bad['domain_roles'].pop(missing)
            with self.assertRaises(ValueError): validate_blueprint(bad,['mathematics','computer_science'])
        for field,value in [('answer_form','number | decision'),('target','word '*21)]:
            bad=blueprint(); bad[field]=value
            with self.assertRaises(ValueError): validate_blueprint(bad,['mathematics','computer_science'])
        self.assertEqual(validate_blueprint(blueprint(),['mathematics','computer_science'])['answer_form'],'code')

    def test_infeasible_forbids_blueprint_and_evidence(self):
        value=screen(input_row())
        value.update(feasible=False,question_plan=None,answer_plans=None,required_key_facts=None,compact_blueprint=None)
        value['selected_samples']={'computer_science':[]}
        refs={'computer_science':{(s['prompt'],s['completion']) for s in screen(input_row())['selected_samples']['computer_science']}}
        self.assertFalse(s4.validate_screening(value,'mathematics',['computer_science'],refs)['feasible'])
        for field,data in [('compact_blueprint',blueprint()),('selected_samples',screen(input_row())['selected_samples'])]:
            bad=copy.deepcopy(value); bad[field]=data
            with self.assertRaises(ValueError): s4.validate_screening(bad,'mathematics',['computer_science'],refs)
        api=FakeAPI(screening=value)
        self.assertEqual(self.process(api)['generated'],0)
        self.assertEqual(len(api.calls),1)

    def test_required_key_facts_and_evidence_constraints(self):
        base=screen(input_row())
        refs={'computer_science':{(s['prompt'],s['completion']) for s in base['selected_samples']['computer_science']}}
        bad=copy.deepcopy(base); bad['required_key_facts']['computer_science'].pop()
        with self.assertRaises(ValueError): s4.validate_screening(bad,'mathematics',['computer_science'],refs)
        bad=copy.deepcopy(base); bad['required_key_facts']['computer_science'][1]=bad['required_key_facts']['computer_science'][0]
        with self.assertRaises(ValueError): s4.validate_screening(bad,'mathematics',['computer_science'],refs)
        bad=copy.deepcopy(base); bad['selected_samples']['computer_science'][0]['prompt']='Unsupplied'
        with self.assertRaises(ValueError): s4.validate_screening(bad,'mathematics',['computer_science'],refs)
        bad=candidate(); bad['used_samples']={'legal':bad['used_samples']['computer_science']}
        with self.assertRaises(ValueError): self.validate_candidate(bad)
        bad=candidate(); bad['used_samples']['computer_science'][0]['completion']='Invented'
        with self.assertRaises(ValueError): self.validate_candidate(bad)

    def test_duplicate_distractor_rejected_and_multiline_preserved(self):
        bad=candidate(); bad['distractor_analysis'][1]['option']='B'
        with self.assertRaisesRegex(ValueError,'exactly once'): self.validate_candidate(bad)
        row=self.validate_candidate()
        self.assertEqual(row['options'],candidate()['options'])
        row['question']='Example:\n    x = 1\nWhich value follows?'
        self.assertEqual(self.validate_candidate(row)['question'],row['question'])

    def test_code_whitespace_and_identifier_case_can_distinguish_outcomes(self):
        row=candidate()
        row['options']['A']='def f(r):\n    for i in range(2):\n        r += 1\n    return r'
        row['options']['B']='def f(r):\n    for i in range(2):\n        r += 1\n        return r'
        self.assertEqual(self.validate_candidate(row)['options'],row['options'])
        row['options']['A']='return A'
        row['options']['B']='return a'
        self.assertEqual(self.validate_candidate(row)['options'],row['options'])
        row['options']['B']=row['options']['A']
        with self.assertRaisesRegex(ValueError,'distinct'): self.validate_candidate(row)

    def test_field_level_lengths_no_truncation_and_short_numbers(self):
        budget=default_budget(2)
        for field in ('question','options.A','total_visible'):
            row=candidate()
            if field=='question': row['question']='word '*76
            elif field=='options.A': row['options']['A']='word '*19
            else:
                row['question']='word '*70
                row['options']={k:(k+' ')*18 for k in 'ABCD'}
            before=copy.deepcopy(row)
            self.assertTrue(any(i['field']==field for i in hard_issues(row,budget)))
            self.assertEqual(row,before)
        row=candidate(); row['question']='Which area?'; row['options']={k:str(n) for k,n in zip('ABCD',range(4))}
        self.assertEqual(hard_issues(row,budget),[])
        row['options']['A']='x='+'1'*220
        self.assertTrue(any(i['unit']=='chars' and i['field']=='options.A' for i in hard_issues(row,budget)))

    def test_budget_configuration_validation_and_extension(self):
        self.assertEqual(default_budget(4)['total_visible_max_words'],190)
        self.assertEqual(default_budget(7)['status'],'uncalibrated_extension')
        override={k:v for k,v in default_budget(2).items() if k!='status'}
        self.assertEqual(validate_budget(override),override)
        for key,value in [('question_max_words',True),('option_max_chars',-1),('question_target_words',[60,40]),('total_visible_max_chars',1)]:
            bad=copy.deepcopy(override); bad[key]=value
            with self.assertRaises(ValueError): validate_budget(bad)
        bad=copy.deepcopy(override); bad.pop('option_max_words')
        with self.assertRaises(ValueError): validate_budget(bad)
        path=self.root/'budget.json'
        path.write_text(json.dumps({'budgets':{'2':override},'blueprint_limits':{'target':30,'dependency_summary':80,'domain_role':40}}))
        budgets,limits=load_budget_file(path)
        self.assertEqual(budget_for(2,budgets)['status'],'custom')
        self.assertEqual(limits['target'],30)

    def test_identity_and_permutation_sync(self):
        original=input_row(); key=plan_key(original); identity=item_id(key,'easy')
        other=copy.deepcopy(original); other['question_plan']='Different original task'
        self.assertNotEqual(plan_key(other),key)
        other=copy.deepcopy(original); other['source_file']='/different/path'
        self.assertEqual(plan_key(other),key)
        row=candidate(); before=copy.deepcopy(row)
        shuffled,mapping=shuffle_options(row,42,identity)
        self.assertEqual(row,before)
        self.assertEqual(shuffle_options(row,42,identity),(shuffled,mapping))
        self.assertEqual(shuffled['options'][shuffled['answer']],row['options'][row['answer']])
        for old,new in zip(row['distractor_analysis'],shuffled['distractor_analysis']):
            self.assertEqual(shuffled['options'][new['option']],row['options'][old['option']])
            self.assertEqual(new['reason'],old['reason'])
            self.assertEqual(new['type'],old['type'])
        code="Matrix A and variable B remain unchanged."
        row['explanation']=code
        self.assertEqual(shuffle_options(row,42,identity)[0]['explanation'],code)
        row['explanation']='Option A is correct.'
        self.assertTrue(any(i['check']=='unsafe_option_reference' for i in hard_issues(row,default_budget(2))))

    def test_blind_audit_whitelist_and_uncertainty(self):
        generated=candidate(); payload=audit_payload(generated,'mathematics',input_row()['sample'],['computer_science'],generated['used_samples'])
        self.assertEqual(set(payload),{'question','options','participating_domains','source_sample','selected_samples'})
        self.assertEqual(set(visible_item({**generated,'construction':blueprint()})),{'question','options'})
        audit=passing_audit(payload)
        validate_audit(audit,['mathematics','computer_science'])
        self.assertEqual(audit_issues(audit,'A'),[])
        for options in ([],['A','B'],['B']):
            bad=copy.deepcopy(audit); bad['correct_options']=options
            validate_audit(bad,['mathematics','computer_science'])
            self.assertTrue(audit_issues(bad,'A'))
        for value in ('fail','uncertain'):
            bad=copy.deepcopy(audit); bad['checks']['self_contained']=value
            self.assertTrue(audit_issues(bad,'A'))
        for value in (False,None):
            bad=copy.deepcopy(audit); bad['domain_necessity']['mathematics']['necessary']=value
            self.assertTrue(audit_issues(bad,'A'))
        bad=copy.deepcopy(audit); bad['domain_necessity']['mathematics']['necessary']=1
        with self.assertRaises(ValueError): validate_audit(bad,['mathematics','computer_science'])

    def test_length_repair_once_and_full_recheck(self):
        def generate(data,n):
            row=candidate()
            if n==1: row['question']='too long '*60
            return row
        api=FakeAPI(generate=generate)
        report=self.process(api)
        self.assertEqual((report['initial_candidates'],report['repair_candidates'],report['accepted']),(3,1,3))
        self.assertEqual(self.rows()[0]['construction']['repair_count'],1)
        attempts=[r for r in self.rows(self.audit) if r['event']=='candidate']
        self.assertEqual([r['status'] for r in attempts],['repairing','accepted','accepted','accepted'])
        repair=[data for prompt,data in api.calls if prompt==s4.REPAIR_PROMPT][0]
        self.assertIn('original_candidate',repair)
        self.assertIn('preserve',repair['feedback'])
        self.assertEqual(api.audit_count,3)

    def test_semantic_repair_rejected_difficulty_and_conflict_not_rekeyed(self):
        def judge(data,n):
            audit=passing_audit(data)
            if n<=2: audit['correct_options']=[k for k in 'ABCD' if k not in audit['correct_options']][:1]
            return audit
        api=FakeAPI(judge=judge)
        report=self.process(api)
        self.assertEqual((report['accepted'],report['final_rejected'],report['repair_candidates']),(2,1,1))
        self.assertEqual([r['difficulty'] for r in self.rows()],['medium','hard'])
        logs=[r for r in self.rows(self.audit) if r['event']=='candidate']
        self.assertEqual([r['status'] for r in logs],['repairing','rejected','accepted','accepted'])
        self.assertEqual(logs[0]['candidate']['options'][logs[0]['candidate']['answer']],candidate()['options']['A'])
        self.assertNotEqual(logs[0]['semantic_audit']['correct_options'],[logs[0]['candidate']['answer']])

    def test_all_semantic_failures_trigger_rewrite_or_rejection(self):
        for failure in ('none','multiple','uncertain','decorative','issue'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                self.output=Path(temp)/'out.jsonl'; self.audit=self.output.with_suffix('.audit.jsonl')
                def judge(data,n):
                    audit=passing_audit(data)
                    if failure=='none': audit['correct_options']=[]
                    elif failure=='multiple': audit['correct_options']=['A','B']
                    elif failure=='uncertain': audit['checks']['single_target']='uncertain'
                    elif failure=='decorative': audit['domain_necessity']['mathematics']['necessary']=False
                    else: audit['issues']=['Missing instance condition']
                    return audit
                report=self.process(FakeAPI(judge=judge))
                self.assertEqual((report['generated'],report['final_rejected'],report['repair_candidates']),(0,3,3))
                self.assertEqual(self.output.read_text(),'')

    def test_second_draft_rechecked_structure_and_lengths(self):
        def generate(data,n):
            row=candidate()
            if n==1: row['question']='word '*76
            elif n==2: row['distractor_analysis'][1]['option']='B'
            return row
        report=self.process(FakeAPI(generate=generate))
        self.assertEqual((report['accepted'],report['final_rejected']),(2,1))
        self.assertEqual(self.rows(self.audit)[2]['issues'][0]['check'],'structure')

    def test_skip_audit_not_quality_passed_and_num_duplicates(self):
        self.source.write_text((json.dumps(input_row())+'\n')*2)
        api=FakeAPI()
        report=self.process(api,skip_semantic_audit=True)
        self.assertEqual((report['processed'],report['duplicate_plans'],report['accepted'],report['debug_accepted']),(2,1,0,3))
        self.assertEqual(api.audit_count,0)
        self.assertTrue(all(r['construction']['semantic_audit_status']=='not_run' for r in self.rows()))
        self.assertEqual(self.rows(self.audit)[-1]['status'],'duplicate')
        self.output=self.root/'limited.jsonl'
        report=s4.process(self.source,self.output,api=FakeAPI(),domain_count=2,num=1,max_tokens=100,
                          max_input_chars=160000,overwrite=False)
        self.assertEqual(report['processed'],1)
        self.assertEqual(report['initial_candidates'],3)

    def test_path_preflight_does_not_truncate_other_output(self):
        for existing in ('output','audit'):
            with self.subTest(existing=existing):
                self.output.unlink(missing_ok=True); self.audit.unlink(missing_ok=True)
                path=self.output if existing=='output' else self.audit
                path.write_text('KEEP')
                with self.assertRaises(FileExistsError): self.process()
                self.assertEqual(path.read_text(),'KEEP')
                self.assertFalse((self.audit if existing=='output' else self.output).exists())
        for path in (self.source,self.output):
            with self.assertRaises(ValueError): self.process(audit_output=path)
        self.output.unlink(missing_ok=True)
        self.output.symlink_to(self.source)
        with self.assertRaises(ValueError): self.process()
        self.assertEqual(len(self.source.read_text().splitlines()),1)

    def test_api_exhaustion_preserves_output_and_is_fatal(self):
        api=FakeAPI(fail_at=4) # screen + accepted easy generate/audit + failing medium
        with self.assertRaisesRegex(APIError,'completed output retained'): self.process(api)
        self.assertEqual(len(self.rows()),1)
        self.assertEqual(self.rows(self.audit)[-1]['event'],'fatal_error')
        self.assertEqual(api.generation_count,1)

    def test_explicit_identity_conflict_and_invalid_schema_are_not_silent(self):
        row=input_row(); row['plan_id']='same-explicit-id'
        other=copy.deepcopy(row); other['question_plan']='Different task'
        self.source.write_text(json.dumps(row)+'\n'+json.dumps(other)+'\n')
        with self.assertRaisesRegex(ValueError,'plan_key collision'):
            self.process()
        self.assertEqual(len(self.rows()),3)
        self.assertEqual(self.rows(self.audit)[-1]['event'],'fatal_error')
        row=candidate(); row['answer']=['A']
        with self.assertRaisesRegex(ValueError,'invalid generation schema'):
            self.validate_candidate(row)
        payload=audit_payload(candidate(),'mathematics',input_row()['sample'],['computer_science'],candidate()['used_samples'])
        for label in ('', 'AB', 1):
            bad=passing_audit(payload); bad['correct_options']=[label]
            with self.assertRaises(ValueError): validate_audit(bad,['mathematics','computer_science'])

    def test_shared_api_json_retries_unchanged(self):
        class Response:
            def __init__(self,content): self.content=content
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def read(self): return self.content.encode()
        api=JSONAPI('https://mock.invalid','fixture','model',retries=1)
        responses=[Response('{"choices":[{"message":{"content":"not JSON"}}]}'),
                   Response('{"choices":[{"message":{"content":"{\\"valid\\":true}"}}]}')]
        with patch('urllib.request.urlopen',side_effect=responses) as request, patch('time.sleep'):
            self.assertEqual(api.chat('',{},lambda v:v,100),{'valid':True})
            self.assertEqual(request.call_count,2)
        with patch('urllib.request.urlopen',side_effect=TimeoutError),patch('time.sleep'):
            with self.assertRaisesRegex(APIError,'after 2 attempts'): api.chat('',{},lambda v:v,100)

    def test_max_input_is_error_not_rejection_or_truncation(self):
        api=FakeAPI()
        with self.assertRaisesRegex(ValueError,'no evidence or code was truncated'):
            s4.process(self.source,self.output,api=api,domain_count=2,num=1,max_tokens=100,max_input_chars=1,overwrite=False)
        self.assertEqual(api.calls,[])
        self.assertEqual(self.rows(self.audit)[-1]['event'],'fatal_error')

    def test_statistic_cli_runs_outside_repository_and_is_offline(self):
        self.process()
        legacy = self.root/'legacy.jsonl'
        rows = self.rows()
        for row in rows:
            row.pop('construction')
            row.pop('item_id')
        legacy.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        report = self.root/'report.json'
        completed = subprocess.run([sys.executable,str(ROOT/'audit_step4_concise.py'),
                                    '--old-root',str(legacy),'--new-root',str(self.output),
                                    '--audit-root',str(self.audit),'--upstream-root',str(self.source),
                                    '--output',str(report)],cwd='/tmp',capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        data=json.loads(report.read_text())
        self.assertEqual(data['matching']['matched_count'],3)
        self.assertEqual(data['audits']['quality_acceptance'],'3/3')
        self.assertEqual(data['matching']['matched_delta_words']['mean'],0)

    def test_prompt_document_matches_actual_prompts(self):
        from _concise_prompts import SCREEN_PROMPT,SYSTEM_PROMPT,AUDIT_PROMPT,REPAIR_PROMPT
        document=(ROOT/'4_generate_fusion_question_prompt_bilingual.md').read_text()
        for prompt in (SCREEN_PROMPT,SYSTEM_PROMPT,AUDIT_PROMPT,REPAIR_PROMPT):
            self.assertIn(prompt.rstrip(),document)

    def test_separate_judge_and_semantic_repair_success(self):
        generation=FakeAPI()
        def judge(data,n):
            audit=passing_audit(data)
            if n==1: audit['checks']['evidence_grounded']='uncertain'
            return audit
        judge_api=FakeAPI(judge=judge)
        judge_api.model='mock-judge'
        report=self.process(generation,judge_api=judge_api)
        self.assertEqual((report['accepted'],report['repair_candidates']),(3,1))
        self.assertEqual(generation.audit_count,0)
        self.assertEqual(judge_api.audit_count,4)
        rows=self.rows()
        self.assertEqual(rows[0]['construction']['repair_count'],1)
        self.assertEqual(rows[0]['construction']['judge_model'],'mock-judge')
        repair=[data for prompt,data in generation.calls if prompt==s4.REPAIR_PROMPT][0]
        self.assertEqual(repair['feedback']['audited_candidate']['options'],judge_api.calls[0][1]['options'])
        for _,payload in judge_api.calls:
            self.assertEqual(set(payload),{'question','options','participating_domains','source_sample','selected_samples'})

    def test_statistics_zero_acceptance_debug_and_ambiguous_matching(self):
        api=FakeAPI(judge=lambda data,n:{**passing_audit(data),'correct_options':[]})
        self.process(api)
        report=stats_script.build_report(self.root,self.root,self.root,self.source)
        self.assertEqual(report['new'],{})
        self.assertEqual(report['audits']['quality_acceptance'],'0/3')
        self.assertIsNone(report['matching']['matched_delta_words'])
        self.assertEqual(len(list(stats_script.records(self.root))),0)
        self.output=self.root/'debug.jsonl'
        self.process(skip_semantic_audit=True)
        report=stats_script.build_report(self.root,self.root,self.root)
        self.assertTrue(all(k.endswith('/not_run') for k in report['new']))
        self.assertEqual(report['audits']['counts']['debug_accepted'],3)
        old=candidate(); old.update({k:v for k,v in input_row().items() if k!='retrieved_samples'},difficulty='easy')
        new={**old,'construction':{'plan_key':plan_key(input_row()),'semantic_audit_status':'passed','scope_change':'target_narrowed'}}
        other=input_row(); other['question_plan']='Different plan'
        pairs=stats_script.pair_records([(Path('old'),1,old)],[(Path('new'),1,new)],
                                        [(Path('input'),1,input_row()),(Path('input'),2,other)])
        self.assertEqual(pairs['matched_count'],1) # exact original fields resolve ambiguity
        old['question_plan']='Unknown revised old plan'
        pairs=stats_script.pair_records([(Path('old'),1,old)],[(Path('new'),1,new)],
                                        [(Path('input'),1,input_row()),(Path('input'),2,other)])
        self.assertEqual(pairs['matched_count'],0)
        self.assertEqual(pairs['unmatched'][0]['status'],'ambiguous_upstream')


if __name__=='__main__':
    unittest.main()
