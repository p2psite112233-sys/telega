import re

def parse_card(text: str) -> dict | None:
    """Парсит данные карты из текста в любом формате."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    all_text = ' '.join(lines)

    # Номер карты — 16 цифр подряд или с разделителями
    card_number = None
    for line in lines:
        digits = re.sub(r'[\s/\-]', '', line)
        if re.fullmatch(r'\d{16}', digits):
            card_number = digits
            break
    if not card_number:
        match = re.search(r'(\d[\d\s/\-]{14,18}\d)', all_text)
        if match:
            digits = re.sub(r'[\s/\-]', '', match.group(1))
            if len(digits) == 16:
                card_number = digits

    # Срок — MM/YY, MMYY, MM YY
    expiry = None
    for line in lines:
        m = re.fullmatch(r'(\d{2})[/\s]?(\d{2,4})', line)
        if m:
            mm = m.group(1)
            yy = m.group(2)[-2:]
            expiry = f"{mm}/{yy}"
            break
    if not expiry:
        m = re.search(r'\b(\d{2})[/\s](\d{2,4})\b', all_text)
        if m:
            expiry = f"{m.group(1)}/{m.group(2)[-2:]}"

    # CVV — 3 цифры на отдельной строке или после "код"
    cvv = None
    for line in lines:
        m = re.fullmatch(r'\d{3}', line)
        if m and line != (expiry or '').replace('/', '')[:3]:
            cvv = line
            break
    if not cvv:
        m = re.search(r'(?:код|cvv|cvc)[:\s]*(\d{3})', all_text, re.IGNORECASE)
        if m:
            cvv = m.group(1)

    if not card_number:
        return None

    return {"number": card_number, "expiry": expiry or "—", "cvv": cvv or "—"}
