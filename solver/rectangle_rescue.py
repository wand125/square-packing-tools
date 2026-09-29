"""Exact-budget rescue of a rectangle candidate using an independent verifier.

Never changes the search state, LP checks, or the source certificate. A numerical
search failure can only be rescued by a complete, matching independent proof.
"""
import argparse,hashlib,json,subprocess,sys
from fractions import Fraction as F
from pathlib import Path


def scale(data,n,reserve):
    reserve=F(reserve)
    if type(n) is not int or n<1 or not 0<reserve<n:raise ValueError('invalid budget/reserve')
    if data.get('atoms') or data.get('atom_weights'):raise ValueError('rectangle-only rescue')
    w=[F(str(x)) for x in data['weights']]
    if not w or len(w)!=len(data['rectangles']) or any(x<0 for x in w):raise ValueError('invalid weights')
    mass=sum(w);target=F(n)-reserve
    if not 0<mass<target:raise ValueError('no expansion budget')
    out=dict(data)
    for k in ['certificate','coverage_lower_bound_exact','last_validation']:out.pop(k,None)
    out.update(weights=[str(x*target/mass) for x in w],mass=float(target),status='RESCUE_CANDIDATE_NOT_VERIFIED',globally_verified=False,
               scaling_experiment=dict(source_mass_exact=str(mass),target_mass_exact=str(target),factor_exact=str(target/mass)))
    assert sum(map(F,out['weights']))==target<n
    return out


def validate_result(candidate,cert,n):
    candidate,cert=Path(candidate),Path(cert)
    d=json.loads(candidate.read_text());meta=json.loads((cert/'certificate_metadata.json').read_text());s=json.loads((cert/'verification_summary.json').read_text())
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    if s['status']!='VERIFIED' or s['angle_cases']!=201:raise ValueError('incomplete proof')
    if meta['source_sha256']!=sha(candidate) or meta['input_sha256']!=s['input_sha256'] or meta['input_sha256']!=sha(cert/'certificate_input.txt'):raise ValueError('proof hash mismatch')
    mass=sum(F(str(x)) for x in d['weights'])
    if F(meta['mass_exact'])!=mass or not 0<mass<n:raise ValueError('proof budget mismatch')
    if F(str(d['L']))!=F(meta['L']) or F(str(d['B']))!=F(meta['B']):raise ValueError('proof geometry mismatch')
    angles=[json.loads(x) for x in (cert/'verified_angles.jsonl').read_text().splitlines()]
    if sorted(x['r'] for x in angles)!=list(range(201)) or any(x['status']!='verified' for x in angles):raise ValueError('missing/unverified directions')
    saved=json.loads((cert/'certified_candidate.json').read_text())
    if saved.get('globally_verified') is not True:raise ValueError('missing verified artifact')
    for key in ['L','B','rectangles','weights']:
        if saved[key]!=d[key]:raise ValueError('certified artifact differs')
    return meta


def rescue(source,n,out,code_dir,reserve=F('0.1'),workers=2):
    source,out,code_dir=Path(source),Path(out),Path(code_dir)
    if workers<1:raise ValueError('workers must be positive')
    raw=source.read_bytes();data=scale(json.loads(raw),n,reserve)
    out.mkdir(parents=True,exist_ok=False)
    (out/'source.json').write_bytes(raw)
    data['scaling_experiment']['source_sha256']=hashlib.sha256(raw).hexdigest()
    candidate=out/'candidate.json';candidate.write_text(json.dumps(data,indent=2));cert=out/'certificate'
    result=dict(status='VERIFYING',n=n,source=str(source.resolve()),source_sha256=hashlib.sha256(raw).hexdigest(),target_mass_exact=str(F(n)-F(reserve)),L=str(data['L']))
    def save():
        temp=out/'result.tmp';temp.write_text(json.dumps(result,indent=2));temp.replace(out/'result.json')
    save()
    try:
        with (out/'verify.log').open('x') as log:
            proc=subprocess.run([sys.executable,str((code_dir/'certify.py').resolve()),str(candidate.resolve()),'--out',str(cert.resolve()),'--workers',str(workers)],stdout=log,stderr=subprocess.STDOUT)
        if proc.returncode:raise RuntimeError(f'verifier exit {proc.returncode}')
        meta=validate_result(candidate,cert,n)
        # The actual verifier artifacts must match the chosen code snapshot.
        for name in ['verify.cpp','run_verify.py']:
            if (cert/name).read_bytes()!=(code_dir/name).read_bytes():raise ValueError('verifier source mismatch')
        result.update(status='CERTIFIED',certificate=str(cert.resolve()),mass_exact=meta['mass_exact'])
    except Exception as e:
        result.update(status='NOT_CERTIFIED',error=str(e));save();raise
    save();return result


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('source',type=Path);a.add_argument('--n',type=int,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--code-dir',type=Path,required=True);a.add_argument('--reserve',type=F,default=F('0.1'));a.add_argument('--workers',type=int,default=2)
    v=a.parse_args();print(json.dumps(rescue(v.source,v.n,v.out,v.code_dir,v.reserve,v.workers)))
