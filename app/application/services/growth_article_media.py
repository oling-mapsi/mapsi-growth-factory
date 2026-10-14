from bs4 import BeautifulSoup


def attach_illustration(html: str, *, asset_id: str, alt: str, placement: str = "after_intro") -> str:
    soup = BeautifulSoup(html, "html.parser")
    url = f"/studio-simple/assets/{asset_id}/image"
    for image in soup.find_all("img", src=url):
        parent = image.parent
        if parent.name == "figure":
            parent.decompose()
        else:
            image.decompose()
    figure = soup.new_tag("figure")
    image = soup.new_tag("img", src=url, alt=alt, loading="lazy")
    figure.append(image)
    if placement == "end":
        soup.append(figure)
    else:
        anchor = soup.find("h2" if placement == "after_heading" else "p")
        if anchor is not None:
            anchor.insert_after(figure)
        else:
            soup.insert(0, figure)
    return str(soup)
