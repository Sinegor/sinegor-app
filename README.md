## Project Overview

SINEGOR LAB is a web application for managing orders and protecting sensitive information in the delivery of AI-assisted legal document analysis and digital document processing services.

It supports the entire administrative workflow, from initial consultation requests and service agreements to delivery of results, order completion, and oversight of document deletion. The application combines a public website, a client portal, an admin panel, and integrations with external services.

Its design reflects the specific requirements of legal practice, with an emphasis on access control, confidentiality, data retention policies, and controlled destruction of personal data. Document analysis and processing take place outside the application itself.

## Project Overview & Features

SINEGOR LAB is a web application for order management, client communication, and information security in the delivery of AI-assisted legal document analysis and digital document processing services.

It combines a public website, a client portal, and an admin panel, covering the entire administrative workflow from initial inquiries to order completion and document destruction. Document analysis and processing take place outside the application itself.

**Key Features:**

- CMS-based content management without code changes.
    
- Passwordless client authentication via one-time links, without self-registration, and two-factor authentication for administrators.
    
- Order management, payment and document handover tracking, signed PDF agreement exchange, review, approval, and secure storage.
    
- Creation, linking, and deletion of Yandex Disk order folders without storing research materials on the application server.
    
- Automatic order completion, retention deadline tracking, and deletion requests.
    
- Email and Telegram notifications with delivery failure tracking and automatic retries.
    
- Access control, category-specific personal data retention periods, documented proof of data destruction where required, and event logging.

## Technology Stack

- **Backend:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic — business logic, data validation, ORM, and database migrations.
    
- **Frontend:** TypeScript, React, React Router (Framework Mode), Node.js — server-side rendering (SSR) and user interfaces.
    
- **Database:** PostgreSQL — application and CMS data storage.
    
- **CMS:** Strapi 5 — public content management.
    
- **API:** OpenAPI and openapi-fetch — type-safe frontend–backend communication.
    
- **Integrations:** Yandex Disk REST API, Telegram Bot API, SMTP.
    
- **Infrastructure:** Linux, Docker, Docker Compose, Nginx.
    
- **Testing:** pytest and Playwright — unit, integration, and end-to-end tests.
    
- **Dependency Management:** uv and npm.

## System Architecture

SINEGOR LAB is built around a modular FastAPI monolith, with a separately deployed frontend and CMS.

- **Nginx** acts as the single public entry point, handling HTTPS and routing requests to application services.
    
- **React Router** renders public pages server-side using Strapi content. Content updates require no frontend rebuild.
    
- **FastAPI** centralizes business logic, authentication, order management, agreements, notifications, and data lifecycle management. The frontend communicates with it through a type-safe API contract.
    
- **PostgreSQL** runs as a single instance with separate databases and credentials for FastAPI and Strapi.
    
- **File Storage:** Signed agreements are kept in private storage. Order materials reside on Yandex Disk.
    
- **Scheduled Jobs** run independently of HTTP request processing.
    
- **Containerization:** Nginx, the frontend, FastAPI, Strapi, and PostgreSQL run in separate Docker containers orchestrated by Docker Compose. Services communicate over an internal network without exposing their internal ports publicly. Persistent data is stored outside container filesystems.
    

This architecture separates responsibilities without introducing microservices.

## AI-Assisted Development Workflow

I used Codex as an AI coding agent to implement SINEGOR LAB while retaining responsibility for key technical, product, and legal decisions.

The development workflow was guided by the following principles:

- Defining functional requirements, application architecture, and acceptance criteria before implementation.
    
- Managing agent context through `AGENTS.md`, project documentation, and a record of approved decisions.
    
- Breaking development into sequential stages with clearly defined tasks, change boundaries, and expected outcomes.
    
- Prohibiting unapproved architectural changes, scope expansion, and refactoring unrelated to the task at hand.
    
- Verifying implementation quality through automated testing, code reviews, functional checks, and dedicated security audits.
    

This approach helps accelerate development with AI while maintaining control over the architecture, software quality, and alignment with the original requirements.

## Security & Data Protection

The application was developed with Russian personal data protection requirements (Federal Law No. 152-FZ) in mind. Security measures are implemented at multiple levels:

- Server-side sessions with protected cookies (HttpOnly, Secure, SameSite=Strict) in production, and password hashing using Argon2id.
    
- Single-use login tokens with limited lifetimes, hash-only token storage, and rate limiting for authentication requests.
    
- CSRF protection and server-side authorization checks, including order ownership verification when accessing protected resources, to prevent insecure direct object references (IDOR).
    
- Security event logging, with tokens, secrets, and document contents excluded from technical logs.

## Testing & Quality Assurance

Automated tests cover three levels:

- **Unit tests:** pytest checks business rules, configuration, and external service adapters.
    
- **Integration tests:** database migrations, model constraints, authorization, status transitions, and concurrent operations against a real PostgreSQL instance.
    
- **End-to-end tests:** Playwright covers the full order management workflow.
    

End-to-end tests run in an isolated environment with real application components and local external service simulators, without production data or resources.

## Deployment & Infrastructure

The application is deployed on a Linux VPS. Operational practices include:

- Separate development and production configurations, environment variable management, and keeping secrets out of version control.
    
- Domain and TLS certificate configuration, secure SSH access, and firewall management.
    
- Database migrations, application builds, and component updates.
    
- Scheduled background jobs and routine maintenance tasks.
    
- Automated database and file storage backups using pg_dump and Restic, including encryption, backup rotation, and recovery testing.
    
- Service health monitoring, error logging, and troubleshooting operational issues.
