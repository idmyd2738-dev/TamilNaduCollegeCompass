from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from models import (
    AdmissionRecord,
    Accreditation,
    Affiliation,
    Campus,
    Department,
    Facility,
    InstitutionFacility,
    FeeStructure,
    Institution,
    Program,
    RecordProvenance,
    University,
    VerificationRecord,
)


class InstitutionRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _matching_ids(
        *,
        name: str | None = None,
        district: str | None = None,
        category: str | None = None,
        institution_type: str | None = None,
        program_name: str | None = None,
        affiliation: str | None = None,
        accreditation: str | None = None,
        facility_code: str | None = None,
    ):
        statement = select(Institution.id)
        if name:
            statement = statement.where(Institution.official_name.ilike(f"%{name}%"))
        if district:
            statement = statement.where(Institution.district.ilike(district))
        if category:
            statement = statement.where(Institution.category.has(code=category))
        if institution_type:
            statement = statement.where(
                Institution.institution_type.has(code=institution_type)
            )
        if program_name:
            statement = statement.where(
                Institution.programs.any(Program.name.ilike(f"%{program_name}%"))
            )
        if affiliation:
            statement = statement.where(
                Institution.affiliations.any(
                    Affiliation.university.has(
                        University.institution.has(
                            Institution.official_name.ilike(f"%{affiliation}%")
                        )
                    )
                )
            )
        if accreditation:
            statement = statement.where(
                Institution.accreditations.any(
                    Accreditation.agency.ilike(f"%{accreditation}%")
                )
            )
        if facility_code:
            facility_institutions = (
                select(InstitutionFacility.institution_id)
                .join(Facility, Facility.id == InstitutionFacility.facility_id)
                .where(Facility.code == facility_code)
            )
            statement = statement.where(Institution.id.in_(facility_institutions))
        return statement

    def count(
        self,
        *,
        name: str | None = None,
        district: str | None = None,
        category: str | None = None,
        institution_type: str | None = None,
        program_name: str | None = None,
        affiliation: str | None = None,
        accreditation: str | None = None,
        facility_code: str | None = None,
    ) -> int:
        matching_ids = self._matching_ids(
            name=name,
            district=district,
            category=category,
            institution_type=institution_type,
            program_name=program_name,
            affiliation=affiliation,
            accreditation=accreditation,
            facility_code=facility_code,
        )
        return self.session.scalar(
            select(func.count()).select_from(matching_ids.subquery())
        ) or 0

    def search(
        self,
        *,
        name: str | None = None,
        district: str | None = None,
        category: str | None = None,
        institution_type: str | None = None,
        program_name: str | None = None,
        affiliation: str | None = None,
        accreditation: str | None = None,
        facility_code: str | None = None,
        sort_by: str = "name",
        limit: int = 25,
        offset: int = 0,
    ) -> list[Institution]:
        matching_ids = self._matching_ids(
            name=name,
            district=district,
            category=category,
            institution_type=institution_type,
            program_name=program_name,
            affiliation=affiliation,
            accreditation=accreditation,
            facility_code=facility_code,
        )
        order_by = (
            Institution.district.asc().nulls_last(),
            Institution.official_name.asc(),
        ) if sort_by == "district" else (Institution.official_name.asc(),)
        statement = (
            select(Institution)
            .options(
                selectinload(Institution.category),
                selectinload(Institution.institution_type),
                selectinload(Institution.provenance),
            )
            .where(Institution.id.in_(matching_ids))
            .order_by(*order_by)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(statement).unique())

    def get_profile(self, institution_id: int) -> Institution | None:
        statement = (
            select(Institution)
            .where(Institution.id == institution_id)
            .options(
                selectinload(Institution.category),
                selectinload(Institution.institution_type),
                selectinload(Institution.provenance).selectinload(RecordProvenance.source),
                selectinload(Institution.campuses)
                .selectinload(Campus.provenance)
                .selectinload(RecordProvenance.source),
                selectinload(Institution.departments)
                .selectinload(Department.provenance)
                .selectinload(RecordProvenance.source),
                selectinload(Institution.programs).selectinload(Program.category),
                selectinload(Institution.programs)
                .selectinload(Program.provenance)
                .selectinload(RecordProvenance.source),
                selectinload(Institution.accreditations)
                .selectinload(Accreditation.provenance)
                .selectinload(RecordProvenance.source),
                selectinload(Institution.university)
                .selectinload(University.provenance)
                .selectinload(RecordProvenance.source),
                selectinload(Institution.affiliations)
                .selectinload(Affiliation.university)
                .selectinload(University.institution),
                selectinload(Institution.affiliations)
                .selectinload(Affiliation.provenance)
                .selectinload(RecordProvenance.source),
                selectinload(Institution.affiliations).selectinload(Affiliation.valid_from_year),
                selectinload(Institution.affiliations).selectinload(Affiliation.valid_until_year),
            )
        )
        return self.session.scalars(statement).unique().one_or_none()

    def compare(self, institution_ids: Sequence[int]) -> list[Institution]:
        unique_ids = list(dict.fromkeys(institution_ids))
        if not unique_ids:
            return []
        found = self.session.scalars(
            select(Institution)
            .where(Institution.id.in_(unique_ids))
            .options(
                selectinload(Institution.category),
                selectinload(Institution.institution_type),
                selectinload(Institution.provenance),
            )
        ).all()
        by_id = {institution.id: institution for institution in found}
        return [by_id[institution_id] for institution_id in unique_ids if institution_id in by_id]


class ProgramRepository:
    def __init__(self, session: Session):
        self.session = session

    def count(
        self,
        *,
        name: str | None = None,
        institution_id: int | None = None,
        category: str | None = None,
    ) -> int:
        statement = select(func.count(Program.id)).join(Program.institution)
        if name:
            statement = statement.where(Program.name.ilike(f"%{name}%"))
        if institution_id is not None:
            statement = statement.where(Program.institution_id == institution_id)
        if category:
            statement = statement.where(Program.category.has(code=category))
        return self.session.scalar(statement) or 0

    def search(
        self,
        *,
        name: str | None = None,
        institution_id: int | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Program]:
        statement = (
            select(Program)
            .join(Program.institution)
            .options(
                selectinload(Program.institution),
                selectinload(Program.category),
                selectinload(Program.department),
                selectinload(Program.provenance),
            )
            .order_by(Program.name, Institution.official_name)
            .limit(limit)
            .offset(offset)
        )
        if name:
            statement = statement.where(Program.name.ilike(f"%{name}%"))
        if institution_id is not None:
            statement = statement.where(Program.institution_id == institution_id)
        if category:
            statement = statement.where(Program.category.has(code=category))
        return list(self.session.scalars(statement).unique())


class AdmissionRepository:
    def __init__(self, session: Session):
        self.session = session

    def for_institution(self, institution_id: int) -> list[AdmissionRecord]:
        statement = (
            select(AdmissionRecord)
            .where(AdmissionRecord.institution_id == institution_id)
            .options(
                selectinload(AdmissionRecord.program),
                selectinload(AdmissionRecord.academic_year),
                selectinload(AdmissionRecord.admission_authority),
                selectinload(AdmissionRecord.admission_route),
                selectinload(AdmissionRecord.counselling_round),
                selectinload(AdmissionRecord.provenance).selectinload(RecordProvenance.source),
            )
            .order_by(AdmissionRecord.academic_year_id.desc(), AdmissionRecord.id)
        )
        return list(self.session.scalars(statement).unique())


class FeeRepository:
    def __init__(self, session: Session):
        self.session = session

    def for_institution(self, institution_id: int) -> list[FeeStructure]:
        statement = (
            select(FeeStructure)
            .where(FeeStructure.institution_id == institution_id)
            .options(
                selectinload(FeeStructure.program),
                selectinload(FeeStructure.academic_year),
                selectinload(FeeStructure.components),
                selectinload(FeeStructure.provenance).selectinload(RecordProvenance.source),
            )
            .order_by(FeeStructure.academic_year_id.desc(), FeeStructure.id)
        )
        return list(self.session.scalars(statement).unique())


class RecommendationRepository:
    def __init__(self, session: Session):
        self.session = session

    def candidates(
        self,
        *,
        district: str | None = None,
        category: str | None = None,
        program_name: str | None = None,
        limit: int = 50,
    ) -> list[Institution]:
        statement = (
            select(Institution)
            .options(
                selectinload(Institution.category),
                selectinload(Institution.institution_type),
                selectinload(Institution.provenance),
            )
            .order_by(Institution.official_name)
            .limit(limit)
        )
        if district:
            statement = statement.where(Institution.district.ilike(district))
        if category:
            statement = statement.where(Institution.category.has(code=category))
        if program_name:
            statement = statement.where(
                Institution.programs.any(Program.name.ilike(f"%{program_name}%"))
            )
        return list(self.session.scalars(statement).unique())


class VerificationRepository:
    def __init__(self, session: Session):
        self.session = session

    def history(self, provenance_id: int) -> list[VerificationRecord]:
        statement = (
            select(VerificationRecord)
            .where(VerificationRecord.provenance_id == provenance_id)
            .options(selectinload(VerificationRecord.source))
            .order_by(VerificationRecord.created_at, VerificationRecord.id)
        )
        return list(self.session.scalars(statement).unique())

    def get_provenance(self, provenance_id: int) -> RecordProvenance | None:
        return self.session.get(RecordProvenance, provenance_id)
