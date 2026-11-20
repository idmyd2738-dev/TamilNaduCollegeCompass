#!/usr/bin/env python3
"""Fast, transactional import of the supplied historical TNEA 2024 CSV into Neon."""
from __future__ import annotations
import argparse, csv, re, sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from sqlalchemy import select
from database import database
from models import (AcademicYear, AdmissionRecord, Department, InformationSource,
                    Institution, InstitutionCategory, InstitutionType, Program,
                    RecordProvenance)

CSV_PATH = Path(__file__).resolve().with_name('tnea_2024_cutoffs_all_college_branch_rows.csv')
SOURCE_URL = 'https://raw.githubusercontent.com/puvicodes/TNEA-Data-CDN/main/tnea_colleges.js'
SOURCE_ORG = 'TNEA-Data-CDN (third-party GitHub compilation)'
SOURCE_TITLE = 'TNEA 2024 college and branch-wise cutoff compilation'
COLUMNS = {'OC':'oc_cutoff','BC':'bc_cutoff','MBC':'mbc_cutoff','SC':'sc_cutoff','ST':'st_cutoff'}

# Explicit legacy-name to TNEA counselling-code matches. Existing records are
# reused by ID; their names and other fields are not overwritten.
LEGACY_INSTITUTION_CODES = {
    'University Colleges of Engineering Arni': '1015',
    'University College of Engineering Ariyalur': '3016',
    'University College of Engineering Dindigul': '5022',
    'University College of Engineering Nagercoil': '4023',
    'University College of Engineering Panruti': '3019',
    'University College of Engineering Pattukkottai': '3021',
    'University College of Engineering Ramanathapuram': '5017',
    'University College of Engineering Thirukkuvalai': '3018',
    'University College of Engineering Tindivanam': '1014',
    'University College of Engineering Villupuram': '1013',
    'University College of Engineering, (BIT) Campus, Tiruchirappalli': '3011',
    'University College of Engineering (VOC College of Engg.), Thoothukudi': '4024',
}

def norm(s): return re.sub(r'[^a-z0-9]+','',(s or '').casefold())
def slug(s): return re.sub(r'[^A-Za-z0-9]+','-',s.strip()).strip('-').upper()[:70] or 'PROGRAM'
def number(s):
    if s is None or not str(s).strip(): return None
    try: n=Decimal(str(s).strip())
    except InvalidOperation: return None
    return n if n >= 0 else None

def main():
    ap=argparse.ArgumentParser()
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    if database.engine.dialect.name != 'postgresql':
        raise RuntimeError(f"Refusing {database.engine.dialect.name}. Set DATABASE_URL to Neon PostgreSQL.")
    with CSV_PATH.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    required={'college_name','counselling_code','department','academic_year',*COLUMNS.values()}
    if not rows or not required.issubset(rows[0]): raise ValueError(f'CSV missing required columns: {required-set(rows[0] if rows else [])}')
    if any((r.get('academic_year') or '').strip()!='2024' for r in rows): raise ValueError('This importer accepts only academic_year=2024.')
    print(f"CSV rows: {len(rows)} | colleges/counselling codes: {len({r['counselling_code'].strip() for r in rows})} | mode: {'APPLY' if args.apply else 'DRY RUN'}",flush=True)
    session=database.session_factory()
    counts={'institutions_created':0,'departments_created':0,'programs_created':0,'cutoffs_created':0,'cutoffs_skipped_missing':0,'cutoffs_skipped_existing':0,'invalid_rows':0}
    try:
        session.begin()
        cat=session.scalar(select(InstitutionCategory).where(InstitutionCategory.code=='engineering'))
        typ=session.scalar(select(InstitutionType).where(InstitutionType.code=='unknown'))
        if cat is None or typ is None: raise RuntimeError('Required lookup rows missing: engineering / unknown.')
        year=session.scalar(select(AcademicYear).where(AcademicYear.label=='2024'))
        if year is None: year=AcademicYear(label='2024'); session.add(year); session.flush()
        source=session.scalar(select(InformationSource).where(InformationSource.source_url==SOURCE_URL))
        if source is None:
            source=InformationSource(source_url=SOURCE_URL,source_organisation=SOURCE_ORG,
                document_title=SOURCE_TITLE,source_document_type='dataset',
                notes='Third-party historical 2024 compilation. Not an official TNEA publication. Original source claims TNEA 2024 official cutoff rankings; independent verification has not been performed. Do not present as current-year cutoffs.')
            session.add(source); session.flush()

        institutions=session.scalars(select(Institution)).all()
        by_name={norm(x.official_name):x for x in institutions}
        by_code={x.institution_code[5:]:x for x in institutions if (x.institution_code or '').startswith('TNEA-')}
        legacy_code_map={}
        for legacy_name, counselling_code in LEGACY_INSTITUTION_CODES.items():
            existing_inst=by_name.get(norm(legacy_name))
            if existing_inst is not None:
                previous=legacy_code_map.get(counselling_code)
                if previous is not None and previous.id != existing_inst.id:
                    raise RuntimeError(f'Conflicting legacy institution mapping for TNEA code {counselling_code}.')
                legacy_code_map[counselling_code]=existing_inst
        code_to_inst={}
        clean=[]
        for i,r in enumerate(rows,2):
            name=(r.get('college_name') or '').strip(); code=(r.get('counselling_code') or '').strip(); branch=(r.get('department') or '').strip()
            if not name or not code or not branch: counts['invalid_rows']+=1; continue
            inst=by_code.get(code) or legacy_code_map.get(code) or by_name.get(norm(name))
            code_to_inst[code]=inst
            clean.append((i,r,name,code,branch))
        new_inst=[]
        for _,_,name,code,_ in clean:
            if code_to_inst[code] is None and not any(x[0]==code for x in new_inst): new_inst.append((code,name))
        inst_provs=[RecordProvenance(source_id=source.id,academic_year_id=year.id,collection_date=date.today(),verification_status='unverified',notes=f'TNEA 2024 third-party dataset; counselling_code={c}. Original verification_status retained in dataset: unverified_third_party_compilation.') for c,n in new_inst]
        session.add_all(inst_provs); session.flush()
        new_inst_objs=[]
        for (code,name),prov in zip(new_inst,inst_provs):
            obj=Institution(official_name=name,institution_code=f'TNEA-{code}',category_id=cat.id,institution_type_id=typ.id,operational_status='unknown',provenance_id=prov.id)
            new_inst_objs.append(obj); code_to_inst[code]=obj; by_name[norm(name)]=obj; by_code[code]=obj
        session.add_all(new_inst_objs); session.flush(); counts['institutions_created']=len(new_inst_objs)

        existing_depts=session.scalars(select(Department)).all()
        dept_map={(d.institution_id,norm(d.name)):d for d in existing_depts}
        dept_keys=[]
        for _,_,_,code,branch in clean:
            inst=code_to_inst[code]; k=(inst.id,norm(branch))
            if k not in dept_map and k not in dept_keys: dept_keys.append(k)
        dept_provs=[RecordProvenance(source_id=source.id,academic_year_id=year.id,collection_date=date.today(),verification_status='unverified',notes='Department name imported from third-party TNEA 2024 dataset; not independently verified.') for _ in dept_keys]
        session.add_all(dept_provs); session.flush()
        dept_objs=[]
        # Build one canonical branch label for each institution/normalized branch key.
        branch_labels={}
        for _,_,_,code,branch in clean: branch_labels.setdefault((code_to_inst[code].id,norm(branch)),branch)
        for key,prov in zip(dept_keys,dept_provs):
            obj=Department(institution_id=key[0],name=branch_labels[key],provenance_id=prov.id); dept_objs.append(obj); dept_map[key]=obj
        session.add_all(dept_objs); session.flush(); counts['departments_created']=len(dept_objs)

        existing_programs=session.scalars(select(Program)).all()
        prog_by_code={(p.institution_id,p.code):p for p in existing_programs if p.code}
        prog_by_dept_name={(p.institution_id,p.department_id,norm(p.name)):p for p in existing_programs}
        prog_keys=[]; row_prog={}
        for rownum,r,name,code,branch in clean:
            inst=code_to_inst[code]; dept=dept_map[(inst.id,norm(branch))]
            pcode=f'TNEA-{code}-{slug(branch)}'[:100]; key=(inst.id,pcode)
            prog=prog_by_code.get(key) or prog_by_dept_name.get((inst.id,dept.id,norm(branch)))
            if prog is None and key not in prog_keys: prog_keys.append(key)
            row_prog[rownum]=(inst,dept,pcode,prog)
        prog_provs=[RecordProvenance(source_id=source.id,academic_year_id=year.id,collection_date=date.today(),verification_status='unverified',notes='Programme/branch imported from third-party TNEA 2024 dataset; not independently verified.') for _ in prog_keys]
        session.add_all(prog_provs); session.flush()
        prog_objs=[]
        key_to_prog={}
        for key,prov in zip(prog_keys,prog_provs):
            inst_id,pcode=key
            item=next(v for v in row_prog.values() if v[0].id==inst_id and v[2]==pcode)
            inst,dept,_,_=item
            obj=Program(institution_id=inst_id,category_id=cat.id,department_id=dept.id,code=pcode,name=dept.name,operational_status='unknown',provenance_id=prov.id)
            prog_objs.append(obj); key_to_prog[key]=obj
        session.add_all(prog_objs); session.flush(); counts['programs_created']=len(prog_objs)
        for rownum,(inst,dept,pcode,prog) in list(row_prog.items()):
            if prog is None: row_prog[rownum]=(inst,dept,pcode,key_to_prog[(inst.id,pcode)])

        existing=session.execute(select(AdmissionRecord.institution_id,AdmissionRecord.program_id,AdmissionRecord.student_category,AdmissionRecord.measurement_type,AdmissionRecord.measurement_unit).where(AdmissionRecord.academic_year_id==year.id,AdmissionRecord.measurement_type=='cutoff_score',AdmissionRecord.measurement_unit=='marks')).all()
        seen={(a,b,c,d,e) for a,b,c,d,e in existing}
        new_records=[]; new_record_provs=[]
        for rownum,r,name,code,branch in clean:
            inst,dept,pcode,prog=row_prog[rownum]
            for category,col in COLUMNS.items():
                val=number(r.get(col))
                if val is None: counts['cutoffs_skipped_missing']+=1; continue
                key=(inst.id,prog.id,category,'cutoff_score','marks')
                if key in seen: counts['cutoffs_skipped_existing']+=1; continue
                seen.add(key)
                new_record_provs.append(RecordProvenance(source_id=source.id,academic_year_id=year.id,collection_date=date.today(),verification_status='unverified',notes=f'Historical 2024 cutoff marks; category={category}; counselling_code={code}; third-party compilation; not independently verified.'))
                new_records.append((inst.id,prog.id,category,val))
        session.add_all(new_record_provs); session.flush()
        session.add_all([AdmissionRecord(institution_id=i,program_id=p,academic_year_id=year.id,student_category=c,measurement_type='cutoff_score',measurement_value=v,measurement_unit='marks',provenance_id=prov.id) for (i,p,c,v),prov in zip(new_records,new_record_provs)])
        counts['cutoffs_created']=len(new_records)
        session.flush()
        if args.dry_run: session.rollback(); print('DRY RUN complete: transaction rolled back; database unchanged.')
        else: session.commit(); print('Import committed.')
        print('Summary:')
        for k,v in counts.items(): print(f'  {k}: {v}')
        if args.apply: print('Expected data label: Historical 2024 cutoff marks — third-party compilation, unverified.')
        return 0
    except Exception:
        session.rollback(); raise
    finally:
        session.close(); database.dispose()

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc: print(f'IMPORT FAILED: {type(exc).__name__}: {exc}',file=sys.stderr); raise SystemExit(1)
