def finish_job(job, handler) -> None:
    try:
        handler(job)
    except Exception:
        pass
    job.status = "complete"
