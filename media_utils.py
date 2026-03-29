def detect_document_type(mime_type: str, file_name: str) -> str:
    lower_name = (file_name or "").lower()
    if mime_type.startswith("image/") or lower_name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image"
    if mime_type == "application/pdf" or lower_name.endswith(".pdf"):
        return "pdf"
    if mime_type.startswith("text/") or lower_name.endswith((".txt", ".md")):
        return "text"
    return "unsupported"
