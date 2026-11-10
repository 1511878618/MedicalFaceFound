const video = document.querySelector("#researchVideo");
const videoPlaceholder = document.querySelector("#videoPlaceholder");
const videoStatus = document.querySelector("#videoStatus");

function assetUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  const url = new URL(value, `${location.origin}/ui-assets/`);
  return ["http:", "https:"].includes(url.protocol) ? url.href : null;
}

async function loadSiteContent() {
  try {
    const response = await fetch("/ui-assets/site-content.json", { cache: "no-cache" });
    if (!response.ok) throw new Error("Site content unavailable");
    const content = await response.json();
    const src = assetUrl(content.video?.src);
    if (content.video?.title) document.querySelector("#videoTitle").textContent = content.video.title;
    if (src) {
      const poster = assetUrl(content.video.poster);
      if (poster) video.poster = poster;
      const captions = assetUrl(content.video.captions);
      if (captions) {
        const track = document.createElement("track");
        Object.assign(track, { kind: "captions", label: "中文字幕", srclang: "zh", src: captions, default: true });
        video.append(track);
      }
      video.addEventListener("error", () => {
        video.hidden = true;
        videoPlaceholder.hidden = false;
        videoStatus.textContent = "视频暂时无法播放，请稍后重试";
      });
      video.addEventListener("loadedmetadata", () => {
        if (!Number.isFinite(video.duration)) return;
        const minutes = Math.floor(video.duration / 60);
        const seconds = String(Math.floor(video.duration % 60)).padStart(2, "0");
        document.querySelector(".film-status").textContent = `${minutes}:${seconds} · 项目宣传片`;
      });
      video.src = src;
      video.hidden = false;
      videoPlaceholder.hidden = true;
    }
    if (Array.isArray(content.institutions) && content.institutions.length) {
      const cards = content.institutions.map((institution) => {
        const link = assetUrl(institution.url);
        const card = document.createElement(link ? "a" : "div");
        card.className = "institution";
        card.dataset.logoStyle = ["wide", "wordmark", "seal"].includes(institution.logoStyle) ? institution.logoStyle : "wordmark";
        if (link) {
          card.href = link;
          card.target = "_blank";
          card.rel = "noopener noreferrer";
          card.setAttribute("aria-label", `${institution.name}官方网站（在新标签页打开）`);
        }
        const logoSlot = document.createElement("span");
        logoSlot.className = "institution-logo";
        const mark = document.createElement("span");
        mark.className = "institution-mark";
        mark.textContent = "LOGO";
        mark.setAttribute("aria-label", `${institution.name} Logo 预留位置`);
        const logo = assetUrl(institution.logo);
        if (logo) {
          const image = document.createElement("img");
          image.alt = institution.name;
          image.addEventListener("error", () => image.replaceWith(mark));
          image.src = logo;
          image.loading = "lazy";
          image.decoding = "async";
          logoSlot.append(image);
        } else logoSlot.append(mark);
        const name = document.createElement("strong");
        name.textContent = institution.name;
        const subtitle = document.createElement("small");
        subtitle.textContent = institution.subtitle || "";
        card.append(logoSlot, name, subtitle);
        return card;
      });
      document.querySelector("#institutionGrid").replaceChildren(...cards);
    }
  } catch (error) {
    // Keep the static introduction and clearly labelled media placeholders usable.
    console.warn("Homepage media configuration could not be loaded.", error);
  }
}

loadSiteContent();

const systems = {
  anthropometric: { number: "01", name: "人体测量", scope: "systemic", annotation: "人体测量 · 整体表型", description: "从整体形态出发，研究面部表征与人体测量指标之间的关联，建立从外在表型理解健康信息的基础。", note: "此类指标反映整体表型，不对应单一器官。" },
  cardiovascular: { number: "02", name: "心血管系统", scope: "regional", x: "56%", y: "25%", annotation: "心血管 · 区域示意", description: "探索面部表征与心血管相关临床指标之间的联系，为跨系统健康表型研究提供新的视角。", note: "研究涉及 HDL-C 等指标；结果来自论文队列评估。" },
  digestive: { number: "03", name: "消化系统", scope: "regional", x: "45%", y: "32%", annotation: "消化 · 区域示意", description: "将研究视角延伸到消化系统相关的临床生物标志物，探索面部表型与这些指标的统计关联。", note: "图中器官用于概念说明，不表示模型直接观察或检查器官。" },
  electrolyte: { number: "04", name: "电解质", scope: "systemic", annotation: "电解质 · 全身性指标", description: "探索面部表征与电解质相关临床指标之间的关系，将体内平衡相关信息纳入多系统研究。", note: "电解质分布于全身，示意图不将其定位到单一器官。" },
  endocrine: { number: "05", name: "内分泌系统", scope: "systemic", annotation: "内分泌 · 跨系统联系", description: "研究面部表型与内分泌相关生物标志物的关联，从多个生理系统相互联系的角度开展探索。", note: "内分泌涉及多个器官与组织，这里以全身范围概括表示。" },
  hematologic: { number: "06", name: "血液系统", scope: "systemic", annotation: "血液 · 全身循环", description: "研究面部表征与血液相关指标之间的联系，进一步理解临床面部照片中蕴含的表型信息。", note: "论文报告了红细胞计数（RBC）等血液指标的预测评估。" },
  immune: { number: "07", name: "免疫系统", scope: "systemic", annotation: "免疫 · 全身性指标", description: "探索面部表征与免疫相关临床指标的关联，将免疫相关表型纳入八类生理系统的研究框架。", note: "免疫活动涉及多个器官与组织，以全身范围进行概念展示。" },
  renal: { number: "08", name: "肾脏系统", scope: "regional", x: "56%", y: "35%", annotation: "肾脏 · 区域示意", description: "探索面部表征与肾脏相关临床指标之间的联系，研究面部基础模型在这一系统中的预测表现。", note: "论文报告了估算肾小球滤过率（eGFR）等指标的预测评估。" }
};

document.querySelectorAll("[data-system]").forEach((button) => {
  button.addEventListener("click", () => {
    const system = systems[button.dataset.system];
    if (!system) return;
    document.querySelectorAll("[data-system]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    document.querySelector("#systemNumber").textContent = `${system.number} / 08`;
    document.querySelector("#systemName").textContent = system.name;
    document.querySelector("#systemScope").textContent = system.scope === "systemic" ? "整体 / 全身性指标" : "系统相关指标";
    document.querySelector("#systemDescription").textContent = system.description;
    document.querySelector("#systemNote").textContent = system.note;
    document.querySelector("#bodyAnnotation").textContent = system.annotation;
    document.querySelector("#bodyMap").dataset.scope = system.scope;
    if (system.x && system.y) {
      const focus = document.querySelector("#bodyFocus");
      focus.style.setProperty("--point-x", system.x);
      focus.style.setProperty("--point-y", system.y);
    }
  });
});

const header = document.querySelector("#homeHeader");
const menuToggle = document.querySelector("#menuToggle");
const navigation = document.querySelector("#homeNavigation");
const compactNavigation = matchMedia("(max-width: 1050px)");

function setMenuOpen(open) {
  menuToggle.setAttribute("aria-expanded", String(open));
  menuToggle.setAttribute("aria-label", open ? "关闭导航菜单" : "打开导航菜单");
  navigation.dataset.open = String(open);
}
header.classList.add("has-menu");
menuToggle.addEventListener("click", () => setMenuOpen(menuToggle.getAttribute("aria-expanded") !== "true"));
navigation.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setMenuOpen(false)));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && menuToggle.getAttribute("aria-expanded") === "true") {
    setMenuOpen(false);
    menuToggle.focus();
  }
});
document.addEventListener("click", (event) => {
  if (!header.contains(event.target)) setMenuOpen(false);
});
compactNavigation.addEventListener("change", () => setMenuOpen(false));

const navigationLinks = [...navigation.querySelectorAll("a[href^='#']")];
const navigationSections = navigationLinks.map((link) => document.querySelector(link.hash)).filter(Boolean);
let scrollScheduled = false;
function updateNavigation() {
  header.classList.toggle("is-scrolled", window.scrollY > 16);
  let current = null;
  for (const section of navigationSections) {
    if (section.getBoundingClientRect().top <= 155) current = section.id;
  }
  navigationLinks.forEach((link) => {
    if (link.hash === `#${current}`) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
  scrollScheduled = false;
}
window.addEventListener("scroll", () => {
  if (!scrollScheduled) {
    scrollScheduled = true;
    requestAnimationFrame(updateNavigation);
  }
}, { passive: true });
window.addEventListener("resize", updateNavigation);
updateNavigation();

if ("IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: .08 });
  document.querySelectorAll("[data-reveal]").forEach((section) => revealObserver.observe(section));
}

// Reflect currently deployed tasks without conflating them with the paper's scope.
fetch('/ready').then(response => { if (!response.ok) throw new Error('unavailable'); return response.json(); }).then(state => {
 const target=document.getElementById('liveModelSummary');
 if(target) target.textContent=state.models?.length && state.inference_ready && state.quality_ready ? `当前体验开放：${state.models.map(model=>model.label).join('、')}。` : (state.capture_ready ? '当前可保存采集资料，模型分析暂未就绪。' : '当前采集服务暂未就绪，请稍后重试。');
}).catch(()=>{ const target=document.getElementById('liveModelSummary'); if(target) target.textContent='在线功能状态暂时无法获取，请进入采集页查看。'; });
