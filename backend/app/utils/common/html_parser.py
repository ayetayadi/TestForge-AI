from bs4 import BeautifulSoup
import re


def clean_html(text: str) -> str:
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")

    for br in soup.find_all("br"):
        br.replace_with("\n")

    return soup.get_text("\n")


def extract_ac_from_html(text: str):
    if not text:
        return []

    soup = BeautifulSoup(text, "html.parser")

    ac_list = []
    current_section = None

    # LIST ITEMS
    for li in soup.find_all("li"):
        content = li.get_text(" ", strip=True)
        if content:
            ac_list.append(content)

    # PARAGRAPHS
    for p in soup.find_all("p"):
        content = p.get_text(" ", strip=True)

        if not content:
            continue

        if ":" in content and len(content.split()) < 5:
            current_section = content.replace(":", "")
            continue

        if current_section:
            ac_list.append(f"{current_section} - {content}")
        else:
            ac_list.append(content)

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if cells:
                ac_list.append(" | ".join(cells))

    ac_list = [re.sub(r"\s+", " ", a).strip() for a in ac_list if a.strip()]

    return ac_list