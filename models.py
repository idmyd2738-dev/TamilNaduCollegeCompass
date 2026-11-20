from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
VECTOR_DOCUMENT = JSON().with_variant(VECTOR(), "postgresql")
VERIFICATION_STATUS_CHECK = (
    "verification_status IN ('unverified', 'pending', 'verified', 'rejected', 'outdated')"
)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProvenanceMixin:
    @declared_attr
    def provenance_id(cls) -> Mapped[int]:
        return mapped_column(
            ForeignKey("record_provenance.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        )

    @declared_attr
    def provenance(cls) -> Mapped["RecordProvenance"]:
        return relationship("RecordProvenance")


class InstitutionCategory(TimestampMixin, Base):
    __tablename__ = "institution_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    institutions: Mapped[list["Institution"]] = relationship(back_populates="category")
    programs: Mapped[list["Program"]] = relationship(back_populates="category")


class InstitutionType(TimestampMixin, Base):
    __tablename__ = "institution_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    institutions: Mapped[list["Institution"]] = relationship(back_populates="institution_type")


class AcademicYear(TimestampMixin, Base):
    __tablename__ = "academic_years"
    __table_args__ = (
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date > start_date",
            name="valid_date_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class InformationSource(TimestampMixin, Base):
    __tablename__ = "information_sources"
    __table_args__ = (
        CheckConstraint(
            "source_url IS NULL OR source_url LIKE 'http://%' OR source_url LIKE 'https://%'",
            name="http_source_url",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_organisation: Mapped[str | None] = mapped_column(String(255))
    document_title: Mapped[str | None] = mapped_column(String(500))
    publication_date: Mapped[date | None] = mapped_column(Date)
    source_document_type: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)

    source_documents: Mapped[list["SourceDocument"]] = relationship(back_populates="source")


class RecordProvenance(TimestampMixin, Base):
    __tablename__ = "record_provenance"
    __table_args__ = (
        CheckConstraint(VERIFICATION_STATUS_CHECK, name="valid_verification_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("information_sources.id", ondelete="RESTRICT"), index=True
    )
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT"), index=True
    )
    collection_date: Mapped[date | None] = mapped_column(Date)
    verification_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="unverified"
    )
    reviewer: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    source: Mapped[InformationSource | None] = relationship()
    academic_year: Mapped[AcademicYear | None] = relationship()
    verification_history: Mapped[list["VerificationRecord"]] = relationship(
        back_populates="provenance", cascade="all, delete-orphan"
    )


class Institution(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "institutions"
    __table_args__ = (
        CheckConstraint(
            "operational_status IN ('active', 'inactive', 'merged', 'closed', 'unknown')",
            name="valid_operational_status",
        ),
        CheckConstraint(
            "establishment_year IS NULL OR establishment_year BETWEEN 1000 AND 2200",
            name="valid_establishment_year",
        ),
        CheckConstraint("length(trim(official_name)) > 0", name="official_name_not_blank"),
        Index("ix_institutions_district_city", "district", "city"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    official_name: Mapped[str] = mapped_column(String(300), nullable=False)
    institution_code: Mapped[str | None] = mapped_column(String(80), unique=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("institution_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    institution_type_id: Mapped[int] = mapped_column(
        ForeignKey("institution_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    city: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    official_website: Mapped[str | None] = mapped_column(String(2048))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    operational_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="unknown"
    )
    establishment_year: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[InstitutionCategory] = relationship(back_populates="institutions")
    institution_type: Mapped[InstitutionType] = relationship(back_populates="institutions")
    campuses: Mapped[list["Campus"]] = relationship(
        back_populates="institution", cascade="all, delete-orphan"
    )
    university: Mapped["University | None"] = relationship(
        back_populates="institution", cascade="all, delete-orphan", uselist=False
    )
    affiliations: Mapped[list["Affiliation"]] = relationship(
        back_populates="institution",
        cascade="all, delete-orphan",
        foreign_keys="Affiliation.institution_id",
    )
    departments: Mapped[list["Department"]] = relationship(
        back_populates="institution", cascade="all, delete-orphan"
    )
    programs: Mapped[list["Program"]] = relationship(
        back_populates="institution", cascade="all, delete-orphan"
    )
    accreditations: Mapped[list["Accreditation"]] = relationship(
        back_populates="institution", cascade="all, delete-orphan"
    )


class Campus(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "campuses"
    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90", name="valid_latitude"
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="valid_longitude"
        ),
        Index("ix_campuses_institution_name", "institution_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    is_main_campus: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    institution: Mapped[Institution] = relationship(back_populates="campuses")
    departments: Mapped[list["Department"]] = relationship(back_populates="campus")


class University(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "universities"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    establishment_act: Mapped[str | None] = mapped_column(String(300))
    registration_code: Mapped[str | None] = mapped_column(String(100), unique=True)

    institution: Mapped[Institution] = relationship(back_populates="university")
    affiliations: Mapped[list["Affiliation"]] = relationship(back_populates="university")


class Affiliation(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "affiliations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'pending', 'unknown')",
            name="valid_affiliation_status",
        ),
        UniqueConstraint(
            "institution_id", "university_id", "valid_from_year_id",
            name="uq_affiliations_institution_university_start",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    university_id: Mapped[int] = mapped_column(
        ForeignKey("universities.institution_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    affiliation_code: Mapped[str | None] = mapped_column(String(100))
    valid_from_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT")
    )
    valid_until_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown")

    institution: Mapped[Institution] = relationship(
        back_populates="affiliations", foreign_keys=[institution_id]
    )
    university: Mapped[University] = relationship(back_populates="affiliations")
    valid_from_year: Mapped[AcademicYear | None] = relationship(foreign_keys=[valid_from_year_id])
    valid_until_year: Mapped[AcademicYear | None] = relationship(foreign_keys=[valid_until_year_id])


class Department(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("institution_id", "code", name="uq_departments_institution_code"),
        UniqueConstraint("institution_id", "name", name="uq_departments_institution_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campus_id: Mapped[int | None] = mapped_column(
        ForeignKey("campuses.id", ondelete="SET NULL"), index=True
    )
    code: Mapped[str | None] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    institution: Mapped[Institution] = relationship(back_populates="departments")
    campus: Mapped[Campus | None] = relationship(back_populates="departments")
    programs: Mapped[list["Program"]] = relationship(back_populates="department")


class Program(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "programs"
    __table_args__ = (
        CheckConstraint(
            "duration_months IS NULL OR duration_months BETWEEN 1 AND 240",
            name="valid_program_duration",
        ),
        CheckConstraint(
            "operational_status IN ('active', 'inactive', 'unknown')",
            name="valid_program_status",
        ),
        Index("ix_programs_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("institution_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    code: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    award: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[str | None] = mapped_column(String(80))
    duration_months: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str | None] = mapped_column(String(40))
    operational_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="unknown"
    )
    description: Mapped[str | None] = mapped_column(Text)

    institution: Mapped[Institution] = relationship(back_populates="programs")
    category: Mapped[InstitutionCategory] = relationship(back_populates="programs")
    department: Mapped[Department | None] = relationship(back_populates="programs")
    specializations: Mapped[list["Specialization"]] = relationship(
        back_populates="program", cascade="all, delete-orphan"
    )


class Specialization(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "specializations"
    __table_args__ = (
        UniqueConstraint("program_id", "name", name="uq_specializations_program_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    program: Mapped[Program] = relationship(back_populates="specializations")


class Accreditation(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "accreditations"
    __table_args__ = (
        CheckConstraint(
            "valid_until IS NULL OR awarded_on IS NULL OR valid_until >= awarded_on",
            name="valid_accreditation_dates",
        ),
        Index("ix_accreditations_institution_agency", "institution_id", "agency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agency: Mapped[str] = mapped_column(String(200), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(80))
    awarded_on: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)

    institution: Mapped[Institution] = relationship(back_populates="accreditations")


class AdmissionAuthority(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "admission_authorities"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False, unique=True)
    authority_type: Mapped[str | None] = mapped_column(String(80))
    jurisdiction: Mapped[str | None] = mapped_column(String(160))
    website: Mapped[str | None] = mapped_column(String(2048))


class AdmissionExam(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "admission_exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    authority_id: Mapped[int | None] = mapped_column(
        ForeignKey("admission_authorities.id", ondelete="SET NULL"), index=True
    )
    code: Mapped[str | None] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False, unique=True)
    exam_level: Mapped[str | None] = mapped_column(String(80))
    website: Mapped[str | None] = mapped_column(String(2048))

    authority: Mapped[AdmissionAuthority | None] = relationship()


class AdmissionCycle(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "admission_cycles"
    __table_args__ = (
        CheckConstraint(
            "application_end IS NULL OR application_start IS NULL "
            "OR application_end >= application_start",
            name="valid_application_dates",
        ),
        CheckConstraint(
            "status IN ('planned', 'open', 'closed', 'cancelled', 'unknown')",
            name="valid_admission_cycle_status",
        ),
        UniqueConstraint("academic_year_id", "name", name="uq_admission_cycles_year_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year_id: Mapped[int] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    application_start: Mapped[date | None] = mapped_column(Date)
    application_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")

    academic_year: Mapped[AcademicYear] = relationship()


class AdmissionRoute(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "admission_routes"
    __table_args__ = (
        UniqueConstraint(
            "admission_cycle_id", "institution_id", "name",
            name="uq_admission_routes_cycle_institution_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    admission_cycle_id: Mapped[int] = mapped_column(
        ForeignKey("admission_cycles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    authority_id: Mapped[int | None] = mapped_column(
        ForeignKey("admission_authorities.id", ondelete="SET NULL"), index=True
    )
    exam_id: Mapped[int | None] = mapped_column(
        ForeignKey("admission_exams.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    route_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    admission_cycle: Mapped[AdmissionCycle] = relationship()
    institution: Mapped[Institution] = relationship()
    authority: Mapped[AdmissionAuthority | None] = relationship()
    exam: Mapped[AdmissionExam | None] = relationship()


class EligibilityCriteria(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "eligibility_criteria"
    __table_args__ = (
        CheckConstraint(
            "minimum_percentage IS NULL OR minimum_percentage BETWEEN 0 AND 100",
            name="valid_minimum_percentage",
        ),
        CheckConstraint(
            "minimum_marks IS NULL OR minimum_marks >= 0",
            name="nonnegative_minimum_marks",
        ),
        CheckConstraint(
            "maximum_age_years IS NULL OR maximum_age_years > 0",
            name="valid_maximum_age",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    admission_route_id: Mapped[int] = mapped_column(
        ForeignKey("admission_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), index=True
    )
    student_category: Mapped[str | None] = mapped_column(String(100))
    minimum_qualification: Mapped[str | None] = mapped_column(String(250))
    minimum_marks: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    minimum_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    maximum_age_years: Mapped[int | None] = mapped_column(Integer)
    criteria_details: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    description: Mapped[str | None] = mapped_column(Text)

    admission_route: Mapped[AdmissionRoute] = relationship()
    program: Mapped[Program | None] = relationship()


class CounsellingRound(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "counselling_rounds"
    __table_args__ = (
        UniqueConstraint("admission_route_id", "round_number", name="uq_counselling_rounds_route_number"),
        CheckConstraint("round_number > 0", name="positive_round_number"),
        CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name="valid_counselling_round_dates",
        ),
        CheckConstraint(
            "status IN ('planned', 'open', 'completed', 'cancelled', 'unknown')",
            name="valid_counselling_round_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    admission_route_id: Mapped[int] = mapped_column(
        ForeignKey("admission_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")

    admission_route: Mapped[AdmissionRoute] = relationship()


class SeatMatrix(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "seat_matrices"
    __table_args__ = (
        CheckConstraint("available_seats >= 0", name="nonnegative_seat_count"),
        UniqueConstraint(
            "admission_route_id", "program_id", "academic_year_id", "student_category", "quota",
            "counselling_round_id", name="uq_seat_matrices_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    admission_route_id: Mapped[int] = mapped_column(
        ForeignKey("admission_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_id: Mapped[int] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    counselling_round_id: Mapped[int | None] = mapped_column(
        ForeignKey("counselling_rounds.id", ondelete="SET NULL"), index=True
    )
    student_category: Mapped[str | None] = mapped_column(String(100))
    quota: Mapped[str | None] = mapped_column(String(100))
    available_seats: Mapped[int] = mapped_column(Integer, nullable=False)

    admission_route: Mapped[AdmissionRoute] = relationship()
    program: Mapped[Program] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    counselling_round: Mapped[CounsellingRound | None] = relationship()


class AdmissionRecord(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "admission_records"
    __table_args__ = (
        CheckConstraint(
            "measurement_type IN ('rank', 'score', 'marks', 'percentage', "
            "'cutoff_score', 'merit_position')",
            name="valid_measurement_type",
        ),
        CheckConstraint("measurement_value >= 0", name="nonnegative_measurement"),
        CheckConstraint(
            "measurement_type != 'percentage' OR measurement_value <= 100",
            name="valid_percentage_measurement",
        ),
        Index(
            "ix_admission_records_program_year",
            "program_id", "academic_year_id", "measurement_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_id: Mapped[int] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    admission_authority_id: Mapped[int | None] = mapped_column(
        ForeignKey("admission_authorities.id", ondelete="SET NULL"), index=True
    )
    admission_route_id: Mapped[int | None] = mapped_column(
        ForeignKey("admission_routes.id", ondelete="SET NULL"), index=True
    )
    counselling_round_id: Mapped[int | None] = mapped_column(
        ForeignKey("counselling_rounds.id", ondelete="SET NULL"), index=True
    )
    student_category: Mapped[str | None] = mapped_column(String(100))
    quota: Mapped[str | None] = mapped_column(String(100))
    measurement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    measurement_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    measurement_unit: Mapped[str] = mapped_column(String(40), nullable=False)

    institution: Mapped[Institution] = relationship()
    program: Mapped[Program] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    admission_authority: Mapped[AdmissionAuthority | None] = relationship()
    admission_route: Mapped[AdmissionRoute | None] = relationship()
    counselling_round: Mapped[CounsellingRound | None] = relationship()


class FeeStructure(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "fee_structures"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="valid_currency_code"),
        Index("ix_fee_structures_institution_year", "institution_id", "academic_year_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    student_category: Mapped[str | None] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    institution: Mapped[Institution] = relationship()
    program: Mapped[Program | None] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    components: Mapped[list["FeeComponent"]] = relationship(
        back_populates="fee_structure", cascade="all, delete-orphan"
    )


class FeeComponent(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "fee_components"
    __table_args__ = (
        CheckConstraint(
            "component_type IN ('tuition', 'admission', 'examination', 'hostel', "
            "'mess', 'transport', 'other')",
            name="valid_fee_component_type",
        ),
        CheckConstraint("amount >= 0", name="nonnegative_fee_amount"),
        UniqueConstraint(
            "fee_structure_id", "component_type", "name",
            name="uq_fee_components_structure_type_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fee_structure_id: Mapped[int] = mapped_column(
        ForeignKey("fee_structures.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    fee_structure: Mapped[FeeStructure] = relationship(back_populates="components")


class Facility(TimestampMixin, Base):
    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    institutions: Mapped[list["InstitutionFacility"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan"
    )


class InstitutionFacility(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "institution_facilities"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "facility_id", "campus_id",
            name="uq_institution_facilities_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    facility_id: Mapped[int] = mapped_column(
        ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    campus_id: Mapped[int | None] = mapped_column(
        ForeignKey("campuses.id", ondelete="CASCADE"), index=True
    )
    details: Mapped[str | None] = mapped_column(Text)

    institution: Mapped[Institution] = relationship()
    facility: Mapped[Facility] = relationship(back_populates="institutions")
    campus: Mapped[Campus | None] = relationship()


class HostelDetail(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "hostel_details"
    __table_args__ = (
        CheckConstraint("capacity IS NULL OR capacity >= 0", name="nonnegative_hostel_capacity"),
        CheckConstraint(
            "availability_status IN ('available', 'unavailable', 'unknown')",
            name="valid_hostel_availability",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campus_id: Mapped[int | None] = mapped_column(
        ForeignKey("campuses.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(150))
    hostel_type: Mapped[str | None] = mapped_column(String(50))
    availability_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="unknown"
    )
    capacity: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[str | None] = mapped_column(Text)

    institution: Mapped[Institution] = relationship()
    campus: Mapped[Campus | None] = relationship()


class Scholarship(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "scholarships"
    __table_args__ = (
        CheckConstraint("amount IS NULL OR amount >= 0", name="nonnegative_scholarship_amount"),
        CheckConstraint("currency IS NULL OR length(currency) = 3", name="valid_scholarship_currency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("programs.id", ondelete="SET NULL"), index=True
    )
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    student_category: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    eligibility: Mapped[str | None] = mapped_column(Text)

    institution: Mapped[Institution] = relationship()
    program: Mapped[Program | None] = relationship()
    academic_year: Mapped[AcademicYear | None] = relationship()


class PlacementReport(TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "placement_reports"
    __table_args__ = (
        CheckConstraint(
            "eligible_students IS NULL OR eligible_students >= 0",
            name="nonnegative_eligible_students",
        ),
        CheckConstraint(
            "placed_students IS NULL OR placed_students >= 0",
            name="nonnegative_placed_students",
        ),
        CheckConstraint(
            "eligible_students IS NULL OR placed_students IS NULL "
            "OR placed_students <= eligible_students",
            name="placed_not_above_eligible",
        ),
        CheckConstraint(
            "median_salary IS NULL OR median_salary >= 0", name="nonnegative_median_salary"
        ),
        CheckConstraint(
            "highest_salary IS NULL OR highest_salary >= 0", name="nonnegative_highest_salary"
        ),
        CheckConstraint(
            "highest_salary IS NULL OR median_salary IS NULL OR highest_salary >= median_salary",
            name="highest_salary_not_below_median",
        ),
        CheckConstraint(
            "currency IS NULL OR length(currency) = 3", name="valid_placement_currency"
        ),
        UniqueConstraint(
            "institution_id", "program_id", "reporting_year",
            name="uq_placement_reports_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("programs.id", ondelete="SET NULL"), index=True
    )
    reporting_year: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    eligible_students: Mapped[int | None] = mapped_column(Integer)
    placed_students: Mapped[int | None] = mapped_column(Integer)
    median_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    highest_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    institution: Mapped[Institution] = relationship()
    program: Mapped[Program | None] = relationship()

    @property
    def placement_percentage(self) -> Decimal | None:
        if (
            self.eligible_students is None
            or self.placed_students is None
            or self.eligible_students <= 0
        ):
            return None
        return (
            Decimal(self.placed_students) * Decimal("100")
            / Decimal(self.eligible_students)
        ).quantize(Decimal("0.01"))


class VerificationRecord(TimestampMixin, Base):
    __tablename__ = "verification_records"
    __table_args__ = (
        CheckConstraint(VERIFICATION_STATUS_CHECK, name="valid_verification_status"),
        Index("ix_verification_records_provenance_created", "provenance_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provenance_id: Mapped[int] = mapped_column(
        ForeignKey("record_provenance.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("information_sources.id", ondelete="RESTRICT"), index=True
    )
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    provenance: Mapped[RecordProvenance] = relationship(back_populates="verification_history")
    source: Mapped[InformationSource | None] = relationship()


class SourceDocument(TimestampMixin, Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "sha256", name="uq_source_documents_source_hash"),
        CheckConstraint("length(sha256) = 64", name="valid_sha256_length"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("information_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(150))
    publication_date: Mapped[date | None] = mapped_column(Date)
    collected_on: Mapped[date | None] = mapped_column(Date)

    source: Mapped[InformationSource] = relationship(back_populates="source_documents")
    document_versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="source_document"
    )


class DataImportJob(TimestampMixin, Base):
    __tablename__ = "data_import_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="valid_import_status",
        ),
        CheckConstraint("rows_read IS NULL OR rows_read >= 0", name="nonnegative_rows_read"),
        CheckConstraint("rows_created IS NULL OR rows_created >= 0", name="nonnegative_rows_created"),
        CheckConstraint("rows_rejected IS NULL OR rows_rejected >= 0", name="nonnegative_rows_rejected"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("information_sources.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_read: Mapped[int | None] = mapped_column(Integer)
    rows_created: Mapped[int | None] = mapped_column(Integer)
    rows_rejected: Mapped[int | None] = mapped_column(Integer)
    error_summary: Mapped[str | None] = mapped_column(Text)

    source: Mapped[InformationSource | None] = relationship()


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("information_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(35))

    source: Mapped[InformationSource] = relationship()
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_document_number"),
        CheckConstraint("version_number > 0", name="positive_document_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions")
    source_document: Mapped[SourceDocument | None] = relationship(back_populates="document_versions")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_number", name="uq_document_chunks_version_number"),
        CheckConstraint("chunk_number >= 0", name="nonnegative_chunk_number"),
        CheckConstraint("token_count IS NULL OR token_count > 0", name="positive_chunk_token_count"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    embedding: Mapped["Embedding | None"] = relationship(
        back_populates="document_chunk", cascade="all, delete-orphan", uselist=False
    )


class Embedding(TimestampMixin, Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        CheckConstraint("dimensions > 0", name="positive_embedding_dimensions"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float] | None] = mapped_column(VECTOR_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document_chunk: Mapped[DocumentChunk] = relationship(back_populates="embedding")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_key_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    title: Mapped[str | None] = mapped_column(String(250))
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('system', 'user', 'assistant', 'tool')", name="valid_message_role"
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    feedback: Mapped[list["ChatbotFeedback"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class ChatbotFeedback(TimestampMixin, Base):
    __tablename__ = "chatbot_feedback"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="valid_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comments: Mapped[str | None] = mapped_column(Text)

    message: Mapped[Message] = relationship(back_populates="feedback")
