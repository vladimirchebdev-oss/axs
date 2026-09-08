# 🕷️ Python Developer (Web Scraping)

Develop a mini-service in Python using NoDriver or CloakBrowser for automated interaction with the ticket website [AXS.com](http://axs.com/)

> ⚠️ The service must bypass **Cloudflare protection** and **support proxy usage**

> 🐳 The service must be fully containerized and run via **Docker**

## 📍 Minimum requirements

1. Use **Chrome v152**
2. Use **NoDriver** or **CloakBrowser** to automate the browser
3. Support **configurable** and **rotating proxies**
4. Successfully bypass **Cloudflare** (Turnstile/captcha)
5. After the protected page loads, either **take** **a** **screenshot** or **add a ticket to the cart**
6. Provide **full Docker setup** **(dockerfile + docker-compose**) so the project runs in containers end-to-end

## ⚙️ Functional requirements

### 🅿️ Core functionality

1. Open a specific event page on [AXS.com](http://axs.com/) (https://shop.axs.com/?c=axs&e=6414022407626854 , https://shop.axs.com/?c=axs&e=4436620017755968)
2. Automatically get through Cloudflare protection without using any external
captcha-solving services
3. After the page successfully loads, perform one of the following actions (save a
screenshot of the page / add a ticket to the cart)
4. Save the final result (either the screenshot and/or logs)

### 🌐 Proxy handling

1. Must work with HTTP, HTTPS, and SOCKS5 proxies
2. Proxies can be set through a config file or environment variables
3. The service should allow switching proxies without restarting
4. Proxies must be checked and validated before being used

> ℹ️We will provide proxies for this test task. If you experience any issues, please inform us

### 🎭 Anti-detect requirements

1. Hide any signs of automation (webdriver flags, navigator values, etc.)
2. Randomize the User-Agent
3. Use a believable browser fingerprint
4. Correctly handle cookies and localStorage
5. Simulate human behavior (small random delays, mouse movement, scrolling)
6. Spoof WebGL, Canvas, and AudioContext fingerprints

### 🐳 Docker requirements

1. Use a production-ready Dockerfile
2. Include docker-compose.yml for easy startup
3. Mount volumes for screenshots and logs
4. Allow configuration through environment variables
5. Keep the image lightweight (multi-stage build preferred)

### ❌ Restrictions

It is **not** allowed to use any external services that solve captchas for you

That means **no** **tools** like **2captcha**, **Anti-Captcha**, **DeathByCaptcha**, **CapMonster**, or any other paid/free captcha solvers

### ⚠️ Remember!

Cloudflare bypass must be implemented exclusively through:

1. Browser automation techniques
2. Anti-detect mechanisms
3. Browser fingerprint spoofing
4. Realistic browser behavior emulation
5. Timing and human-like interactions


🆘 Help? Message me here in the chat or reach out via Telegram **@alexandra_m_02**