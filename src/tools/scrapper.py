# import requests
# from bs4 import BeautifulSoup


# def test_scrape(url):
#     print("=" * 60)
#     print(f"Testing URL: {url}")
#     print("=" * 60)

#     headers = {
#         "User-Agent": (
#             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#             "AppleWebKit/537.36 "
#             "Chrome/120.0 Safari/537.36"
#         )
#     }

#     try:
#         response = requests.get(
#             url,
#             headers=headers,
#             timeout=15,
#             allow_redirects=True
#         )

#         print("\n---- REQUEST STATUS ----")
#         print("Status Code :", response.status_code)
#         print("Final URL   :", response.url)
#         print("Content Size:", len(response.text))
#         print("Content-Type:", response.headers.get("Content-Type"))

#         html_doc = response.text.lower()

#         # ---- BLOCK DETECTION ----
#         if "access denied" in html_doc:
#             print("🚫 BLOCKED: Access Denied page")
#             return

#         if "captcha" in html_doc:
#             print("🚫 BLOCKED: CAPTCHA detected")
#             return

#         if "institutional login" in html_doc:
#             print("🚫 PAYWALL / LOGIN WALL")
#             return

#         soup = BeautifulSoup(response.text, "lxml")

#         # ---- ABSTRACT CHECK ----
#         h2 = soup.find(
#             lambda tag:
#             tag.name in ("h2", "h3", "h4")
#             and "abstract" in tag.get_text(strip=True).lower()
#         )

#         if h2:
#             print("✅ Abstract heading detected")
#         else:
#             print("⚠️ No Abstract heading found")

#         print("Page Title:",
#               soup.title.get_text(strip=True)
#               if soup.title else "None")

#     except Exception as e:
#         print("ERROR:", e)


# if __name__ == "__main__":
#     test_url = [
#         "https://www.ideals.illinois.edu/items/127751"
#     ]

#     for u in test_url:
#         test_scrape(u)

# # if __name__ == "__main__":
# #     # url = "https://wikipedia.org"   # ← CHANGE THIS
# #     # test_scrape(url)
# #     # response = requests.get(url)
# #     # test_url = ['https://pubs.acs.org/doi/abs/10.1021/acsomega.4c03017', 'https://www.sciencedirect.com/science/article/pii/S2214860422005711', 
# #     #             'https://advanced.onlinelibrary.wiley.com/doi/abs/10.1002/adma.202515033','https://onlinelibrary.wiley.com/doi/abs/10.1002/smtd.202301569',
# #     #             'https://www.sciencedirect.com/science/article/pii/S1526612521007362','https://www.ideals.illinois.edu/items/127751','https://www.mdpi.com/2073-4360/17/5/680','https://par.nsf.gov/servlets/purl/10429500']
# #     test_url = ['https://advanced.onlinelibrary.wiley.com/doi/abs/10.1002/adma.202515033']
    
# #     for i in test_url:
# #         test_scrape(i)




import requests

doi = "10.1002/adma.202515033"

url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
params = {"fields": "title,abstract"}

r = requests.get(url, params=params)
print(r.json()["abstract"])
