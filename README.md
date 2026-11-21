# ED Khabar – khud update hone wali news website

Yeh website Enforcement Directorate (ED) ki khabrein **har 2 ghante mein apne aap** update karti hai. GitHub par yeh poori tarah **free** chalti hai, aur iske liye koi server nahi chahiye.

## Kaise kaam karti hai
- `scripts/fetch_news.py`: Google News (Hindi + English) se ED wali headlines laata hai, unhe category mein daalta hai (Chhapemari, Giraftari, Summons, Kurki, Adalat, FEMA) aur `news.json` mein save karta hai.
- `.github/workflows/update-news.yml`: GitHub Actions is script ko har 2 ghante chalata hai aur nayi khabrein commit kar deta hai.
- `index.html`: website. Yeh `news.json` padhti hai aur khuli rehne par har 15 minute mein refresh hoti hai.

## Live kaise karein (10 minute)
1. [github.com](https://github.com) par account banayein, phir **New repository** banayein (jaise `ed-khabar`). Use **Public** rakhein.
2. **Add file → Upload files** par jaakar is zip ki saari files upload karein. Folder structure waisa hi rehna chahiye. `.github` folder zaroor upload karein. Agar woh browser se upload na ho, to **Add file → Create new file** mein naam `.github/workflows/update-news.yml` likhkar content paste kar dein.
3. **Settings → Pages** mein jaayein. **Source:** *Deploy from a branch* chunein, branch `main` aur folder `/ (root)`, phir **Save** dabayein.
4. **Settings → Actions → General** mein jaayein. *Workflow permissions* mein **Read and write permissions** chunein aur Save karein.
5. **Actions** tab mein jaakar *Update ED news* chunein, phir **Run workflow** dabayein. Isse pehli baar news turant aa jayegi.
6. 1-2 minute mein site `https://<aapka-username>.github.io/ed-khabar/` par live ho jayegi.

## Apna domain (optional)
**Settings → Pages → Custom domain** mein apna domain daalein (jaise `edkhabar.in`). Phir domain provider ki DNS settings mein GitHub ke bataye hue records add karein.

## Badlaav
- **Update kitni baar ho:** workflow file mein `cron: "17 */2 * * *"` badlein. Jaise `*/1` likhne par har ghante update hoga.
- **Kitne din ki khabrein rahein:** `fetch_news.py` mein `KEEP_DAYS` badlein.
- **Search keywords:** `fetch_news.py` mein `FEEDS` badlein.

## Dhyan dein
- Site sirf headline aur source dikhati hai. Poori khabar original website par khulti hai.
- Agar repo mein 60 din tak koi activity na ho to GitHub scheduled workflows band kar deta hai. Bot ke commits activity mein gine jaate hain, isliye aam taur par yeh chalta rehta hai. Phir bhi kabhi band ho jaye to Actions tab se dobara **Enable** kar dein.
- Yeh ek independent site hai, ED ya sarkar se iska koi sambandh nahi hai.
