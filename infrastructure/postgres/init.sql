-- PostgreSQL 초기화 스크립트
-- uuid-ossp: UUID 생성 함수 제공
-- pg_trgm: 약품명 퍼지 검색(trigram similarity)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
