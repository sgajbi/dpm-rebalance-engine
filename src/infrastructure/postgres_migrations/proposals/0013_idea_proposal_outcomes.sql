ALTER TABLE proposal_idea_review_realizations
    ADD COLUMN IF NOT EXISTS proposal_id TEXT NULL;

ALTER TABLE proposal_idea_review_realizations
    DROP CONSTRAINT ck_proposal_idea_realization_status,
    DROP CONSTRAINT ck_proposal_idea_review_work_status,
    DROP CONSTRAINT ck_proposal_idea_realization_work_posture;

ALTER TABLE proposal_idea_review_realizations
    ADD CONSTRAINT uq_proposal_idea_realization_proposal UNIQUE (proposal_id),
    ADD CONSTRAINT fk_proposal_idea_realization_proposal
        FOREIGN KEY (proposal_id) REFERENCES proposal_records(proposal_id) ON DELETE RESTRICT,
    ADD CONSTRAINT ck_proposal_idea_realization_status
        CHECK (
            current_status IN (
                'ACCEPTED_FOR_REVIEW',
                'PROPOSAL_LINKED',
                'ADVISORY_REJECTED',
                'ADVISORY_CANCELLED',
                'ADVISORY_EXPIRED',
                'ADVISORY_COMPLETED',
                'REJECTED_BEFORE_WORK'
            )
        ),
    ADD CONSTRAINT ck_proposal_idea_review_work_status
        CHECK (
            review_work_status IS NULL
            OR review_work_status IN ('PENDING_ADVISER_REVIEW', 'PROPOSAL_LINKED', 'CLOSED')
        ),
    ADD CONSTRAINT ck_proposal_idea_realization_work_posture
        CHECK (
            (
                current_status = 'ACCEPTED_FOR_REVIEW'
                AND review_work_id IS NOT NULL
                AND review_work_status = 'PENDING_ADVISER_REVIEW'
                AND proposal_id IS NULL
            ) OR (
                current_status = 'PROPOSAL_LINKED'
                AND review_work_id IS NOT NULL
                AND review_work_status = 'PROPOSAL_LINKED'
                AND proposal_id IS NOT NULL
            ) OR (
                current_status IN (
                    'ADVISORY_REJECTED',
                    'ADVISORY_CANCELLED',
                    'ADVISORY_EXPIRED',
                    'ADVISORY_COMPLETED'
                )
                AND review_work_id IS NOT NULL
                AND review_work_status = 'CLOSED'
                AND proposal_id IS NOT NULL
            ) OR (
                current_status = 'REJECTED_BEFORE_WORK'
                AND review_work_id IS NULL
                AND review_work_status IS NULL
                AND proposal_id IS NULL
            )
        );

ALTER TABLE proposal_idea_realization_outcomes
    DROP CONSTRAINT ck_proposal_idea_realization_outcome_status,
    DROP CONSTRAINT ck_proposal_idea_realization_outcome_reason,
    DROP CONSTRAINT ck_proposal_idea_realization_outcome_initial_posture;

ALTER TABLE proposal_idea_realization_outcomes
    ADD CONSTRAINT fk_proposal_idea_realization_outcome_proposal
        FOREIGN KEY (proposal_id) REFERENCES proposal_records(proposal_id) ON DELETE RESTRICT,
    ADD CONSTRAINT ck_proposal_idea_realization_outcome_status
        CHECK (
            status IN (
                'ACCEPTED_FOR_REVIEW',
                'PROPOSAL_LINKED',
                'ADVISORY_REJECTED',
                'ADVISORY_CANCELLED',
                'ADVISORY_EXPIRED',
                'ADVISORY_COMPLETED',
                'REJECTED_BEFORE_WORK'
            )
        ),
    ADD CONSTRAINT ck_proposal_idea_realization_outcome_reason
        CHECK (
            reason_code IN (
                'idea_conversion_accepted_for_adviser_review',
                'idea_conversion_rejected_before_advisory_work',
                'advise_proposal_linked',
                'advise_proposal_rejected',
                'advise_proposal_cancelled',
                'advise_proposal_expired',
                'advise_proposal_workflow_completed'
            )
        ),
    ADD CONSTRAINT ck_proposal_idea_realization_outcome_posture
        CHECK (
            (
                status = 'ACCEPTED_FOR_REVIEW'
                AND review_work_id IS NOT NULL
                AND proposal_id IS NULL
                AND terminal = FALSE
            ) OR (
                status = 'REJECTED_BEFORE_WORK'
                AND review_work_id IS NULL
                AND proposal_id IS NULL
                AND terminal = TRUE
            ) OR (
                status = 'PROPOSAL_LINKED'
                AND review_work_id IS NOT NULL
                AND proposal_id IS NOT NULL
                AND terminal = FALSE
            ) OR (
                status IN (
                    'ADVISORY_REJECTED',
                    'ADVISORY_CANCELLED',
                    'ADVISORY_EXPIRED',
                    'ADVISORY_COMPLETED'
                )
                AND review_work_id IS NOT NULL
                AND proposal_id IS NOT NULL
                AND terminal = TRUE
            )
        );
