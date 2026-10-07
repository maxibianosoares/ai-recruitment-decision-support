"""
TASK I: Application.ai_status values in one place.

ai_status is a plain CharField (no choices=), so these are conventions,
not DB constraints -- keeping them as named constants stops typos and
documents the state machine.

    QUEUED             apply_job() saved the application and PDF.
      |
    EXTRACTING         worker claimed it and is reading the document.
      |-- DOCUMENT_INVALID    corrupt / encrypted / unreadable PDF
      |-- EXTRACTION_FAILED   valid PDF but text missing, too little,
      |                       low quality, or pages could not be read
      |
    EXTRACTED          text is complete enough; saved on the candidate.
      |
    PROCESSING         recruitment_pipeline() is running.
      |-- FAILED              AI pipeline failure (unchanged meaning)
      |
    SUCCESS            AI finished; Notification #1 is sent now.

DOCUMENT_INVALID and EXTRACTION_FAILED never reach the AI pipeline and
never trigger Notification #1. They are "retryable": the candidate may
re-upload a better file for the same job.
"""

QUEUED = "QUEUED"
EXTRACTING = "EXTRACTING"
EXTRACTED = "EXTRACTED"
PROCESSING = "PROCESSING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"
DOCUMENT_INVALID = "DOCUMENT_INVALID"
EXTRACTION_FAILED = "EXTRACTION_FAILED"

# Statuses where the candidate may submit a replacement CV.
RETRYABLE_DOCUMENT_STATUSES = (DOCUMENT_INVALID, EXTRACTION_FAILED)

# Statuses a worker that just started cannot legitimately own.
IN_FLIGHT_STATUSES = (EXTRACTING, EXTRACTED, PROCESSING)

# Human-readable text for candidate-facing pages.
DISPLAY = {
    QUEUED: "Queued for screening",
    EXTRACTING: "Reading your CV",
    EXTRACTED: "CV read, starting AI screening",
    PROCESSING: "AI screening in progress",
    SUCCESS: "AI screening completed",
    FAILED: "AI screening could not be completed",
    DOCUMENT_INVALID: "CV could not be opened - please re-upload",
    EXTRACTION_FAILED: "CV text could not be read completely - please re-upload",
}