# 사이트 상황판

배포한 웹사이트를 GitHub Actions로 5분마다 점검하고, 결과를 GitHub Pages 대시보드로 보여줍니다. 사이트가 다운되거나 복구되면 텔레그램으로 알립니다. PC가 꺼져 있어도 동작합니다.

점검 항목: 가동 여부(HTTP 코드), 응답 시간, 24시간·7일 가동률, SSL 인증서 만료일, 장애 기록, 방문자 수(GoatCounter 연결 시).

## 1. 사이트 주소 넣기

`sites.json`의 `url`을 실제 배포 주소로 바꿉니다.

- car(owner-note): Cloudflare 대시보드 → Workers & Pages → 프로젝트 → `https://이름.pages.dev`
  (GitHub 저장소 Settings → Variables의 `SITE_URL`에도 있습니다)
- appliance-tracker: Netlify 대시보드 → 사이트 → `https://이름.netlify.app`

사이트를 더 넣으려면 항목을 추가하면 됩니다. 이름을 바꾸면 기록이 새로 시작됩니다.

## 2. GitHub에 올리기

1. GitHub에서 새 저장소를 만듭니다(예: `site-monitor`). 무료로 Pages를 쓰려면 **Public**이어야 합니다.
2. 이 폴더를 올립니다.
   ```bash
   git init && git add . && git commit -m "Site monitor" && git branch -M main
   git remote add origin https://github.com/<계정>/site-monitor.git && git push -u origin main
   ```
3. 저장소 **Settings → Pages**: Source를 `Deploy from a branch`, 브랜치 `main`, 폴더 `/docs`로 저장합니다.
4. **Actions** 탭 → `Site monitor` → `Run workflow`로 첫 점검을 돌립니다. 이후 5분마다 자동 실행됩니다.
5. 대시보드 주소: `https://<계정>.github.io/site-monitor/`

## 3. 텔레그램 알림 (선택)

travel-trend-tracker에서 쓰는 봇 토큰과 chat id를 그대로 써도 됩니다.
저장소 **Settings → Secrets and variables → Actions → New repository secret**에 추가합니다.

| 이름 | 값 |
|---|---|
| `TELEGRAM_TOKEN` | 봇 토큰 |
| `TELEGRAM_CHAT_ID` | chat id |

알림이 오는 경우: 다운(한 번 재시도 후에도 실패), 복구(다운 시간 포함), SSL 만료 14일 이내(하루 한 번).

## 4. 방문자 통계 (선택, GoatCounter)

1. https://www.goatcounter.com 에서 무료 가입하고 사이트 코드(예: `ownernote`)를 만듭니다. 사이트마다 하나씩 만듭니다.
2. 각 사이트의 HTML `</body>` 앞에 넣습니다.
   ```html
   <script data-goatcounter="https://ownernote.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>
   ```
   - car: `scripts/build.js`가 만드는 HTML 템플릿
   - appliance-tracker: `public_template.html`
3. GoatCounter → Settings → API에서 토큰을 만들고(권한: Read statistics) 저장소 시크릿 `GOATCOUNTER_TOKEN`에 넣습니다.
   사이트마다 다른 계정이라면 같은 계정 아래 사이트를 추가해 토큰 하나로 쓰는 편이 간단합니다.
4. `sites.json`의 `goatcounter`에 사이트 코드를 적습니다.

방문자 수는 1시간에 한 번 갱신됩니다.

## 참고

- GitHub의 예약 실행은 붐비는 시간에 몇 분~십여 분 늦어질 수 있습니다. 점검이 30분 넘게 멈추면 대시보드 상단에 표시됩니다.
- 점검 결과는 `docs/data/`에 커밋되며 응답 기록은 7일, 장애 기록은 최근 30건을 보관합니다.
- 로컬에서 한 번 돌려보기: `python monitor.py` (결과는 `docs/data/`에 생김)
