def run_with_retries(operation, retries: int):
    for _ in range(retries):
        try:
            return operation()
        except TimeoutError:
            pass
    raise RuntimeError("operation failed")
