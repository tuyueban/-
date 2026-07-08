const API_BASE = (() => {
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    if (["8000"].includes(window.location.port)) {
      return window.location.origin;
    }
  }
  return "http://127.0.0.1:8000";
})();

const API_ORIGINS = (() => {
  const origins = [API_BASE];
  ["http://127.0.0.1:8000"].forEach((origin) => {
    if (!origins.includes(origin)) origins.push(origin);
  });
  return origins;
})();

const STYLE_DEFS = [
  { name: "流行", color: "#13b981", desc: "旋律清晰、情绪表达直接的主流流行音乐。", tags: ["抒情", "青春", "回忆", "情歌", "治愈"] },
  { name: "说唱 / Hip-Hop", color: "#2f80ed", desc: "强调节奏、Flow 与态度表达的城市音乐风格。", tags: ["Flow", "街头", "态度", "现实", "Battle"] },
  { name: "电子 / Dance", color: "#31c6c1", desc: "由电子合成器和节拍驱动的舞曲或实验流行。", tags: ["合成器", "节拍", "舞曲", "未来感", "律动"] },
  { name: "国风 / 古风", color: "#a98cf5", desc: "融合传统文化意象、古典旋律与现代流行编曲。", tags: ["古风", "戏腔", "国潮", "江湖", "山河"] },
  { name: "OST / 影视音乐", color: "#6d8fb5", desc: "与影视、综艺、剧集传播绑定的歌曲类型。", tags: ["剧情", "片尾", "共鸣", "影视", "角色"] },
  { name: "R&B / Soul", color: "#f45f83", desc: "重视律动、转音和细腻情绪的流行分支。", tags: ["律动", "转音", "氛围", "柔和", "夜晚"] },
  { name: "摇滚", color: "#8f63df", desc: "强调吉他、鼓组和现场能量的强表达音乐。", tags: ["吉他", "现场", "力量", "呐喊", "乐队"] },
  { name: "民谣", color: "#f2994a", desc: "以叙事、原声器乐和生活感见长。", tags: ["叙事", "原声", "城市", "故事", "温暖"] },
  { name: "ACG / 二次元", color: "#85c9ff", desc: "围绕动画、游戏、虚拟内容传播的音乐。", tags: ["动画", "游戏", "热血", "角色", "幻想"] },
  { name: "古典", color: "#8fa1b3", desc: "以古典作曲体系、器乐演奏和严肃音乐传统为核心。", tags: ["器乐", "交响", "钢琴", "室内乐", "古典"] },
  { name: "短视频热歌", color: "#ff9f6e", desc: "在短视频平台传播明显、节奏记忆点突出的热门歌曲。", tags: ["短视频", "抖音", "快手", "传播", "记忆点"] },
];

const PRIMARY_STYLE_NAMES = new Set(STYLE_DEFS.map((style) => style.name));

const state = {
  dashboard: null,
  daily: [],
  weekly: [],
  weeklyMessage: "",
  artists: [],
  rising: [],
  newSongs: [],
  interactionHeat: [],
  styleBuckets: [],
  styleMeta: null,
  activeStyle: "",
  activeList: "",
  activeView: "dashboard",
  crossPlatform: null,
  explorer: {
    sessionId: "",
    result: null,
    aiSearch: null,
  },
  ai: {
    song: null,
    artist: null,
  },
  expanded: {
    style: false,
  },
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  let lastError = null;
  for (const origin of API_ORIGINS) {
    try {
      const response = await fetch(`${origin}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      if (!response.ok) {
        const text = await response.text();
        let message = text || `HTTP ${response.status}`;
        try {
          const data = JSON.parse(text);
          message = data.detail || message;
        } catch (_error) {
          // Keep the raw response text.
        }
        lastError = new Error(`${origin} ${message}`);
        continue;
      }
      return response.json();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("接口请求失败");
}

function setApiStatus(text) {
  $("#apiStatus").textContent = text;
  const wrap = $("#apiStatus").closest(".sidebar-status");
  if (wrap) wrap.classList.toggle("is-offline", /未|失败|异常/.test(text));
}

async function checkBackend() {
  await api("/health");
  setApiStatus("数据已连接");
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("active");
  window.setTimeout(() => node.classList.remove("active"), 2600);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function formatNumber(value) {
  const number = Number(value || 0);
  if (number >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return `${Math.round(number)}`;
}

function formatPercent(value) {
  const number = Number(value || 0);
  return `${Math.round(number)}%`;
}

function platformCode(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("netease") || text.includes("网易") || text.includes("163")) return "netease";
  if (text.includes("qq") || text.includes("tencent")) return "qq";
  if (text.includes("kugou") || text.includes("酷狗")) return "kugou";
  return text || "unknown";
}

function platformName(value) {
  const names = {
    netease: "网易云音乐",
    qq: "QQ音乐",
    kugou: "酷狗音乐",
  };
  const code = platformCode(value);
  return names[code] || value || "未知平台";
}

function normalizePlatformName(value) {
  return platformName(value);
}

function sortPlatformNames(values) {
  const order = { netease: 0, qq: 1, kugou: 2 };
  return Array.from(new Set((values || []).filter(Boolean).map(normalizePlatformName)))
    .sort((a, b) => (order[platformCode(a)] ?? 99) - (order[platformCode(b)] ?? 99));
}

const MAIN_PLATFORMS = [
  { code: "netease", name: "网易云音乐", color: "#00856f" },
  { code: "qq", name: "QQ音乐", color: "#f2994a" },
  { code: "kugou", name: "酷狗音乐", color: "#2f80ed" },
];

function platformShort(value) {
  const shorts = {
    netease: "网",
    qq: "Q",
    kugou: "酷",
  };
  return shorts[platformCode(value)] || "音";
}

function platformBadge(value) {
  const code = platformCode(value);
  return `<span class="platform-badge ${code}" title="${escapeHtml(platformName(value))}">${escapeHtml(platformShort(value))}</span>`;
}

function platformBadges(values) {
  const order = { netease: 0, qq: 1, kugou: 2 };
  const platforms = Array.from(new Set((values || []).filter(Boolean).map(platformCode)))
    .sort((a, b) => (order[a] ?? 99) - (order[b] ?? 99));
  return platforms.length ? platforms.map(platformBadge).join("") : "";
}

function getSongSourcePlatformNames(item) {
  const directValues = item?.source_platform_names || item?.platform_names;
  if (Array.isArray(directValues) && directValues.length) return sortPlatformNames(directValues);

  const platformRows = Array.isArray(item?.platforms) ? item.platforms : [];
  const platformNames = platformRows
    .map((row) => (typeof row === "string" ? row : row?.platform_name || row?.platform || row?.name))
    .filter(Boolean);
  if (platformNames.length) return sortPlatformNames(platformNames);

  const performanceRows = platformPerformanceItems(item?.platform_performance || item?.platformPerformance || item);
  const enteredNames = performanceRows
    .filter(isEnteredPlatform)
    .map((row) => row.platform_name || row.platform || row.name)
    .filter(Boolean);
  if (enteredNames.length) return sortPlatformNames(enteredNames);

  if (Array.isArray(item?.source_platforms) && item.source_platforms.length) {
    return sortPlatformNames(item.source_platforms);
  }

  return [];
}

function sourcePlatforms(item) {
  return getSongSourcePlatformNames(item);
}

function heatValue(item) {
  return Number(
    item.adjusted_heat
    || item.adjustedHeat
    || item.heat_score
    || item.avg_heat_score
    || item.new_song_score
    || item.interaction_heat_score
    || item.artist_heat_score
    || item.total_score
    || 0
  );
}

function coverageCount(item) {
  const count = Number(item.coverage_count || item.coverageCount || item.platform_count || 0);
  return count > 0 ? Math.min(count, 3) : null;
}

function coverageLabel(item) {
  const count = coverageCount(item);
  return count ? `${count}/3` : "";
}

function confidenceLabel(item) {
  const label = item.confidence_level || item.confidenceLevel || item.confidence_label;
  if (label) return label;
  const count = coverageCount(item);
  if (count >= 3) return "高";
  if (count === 2) return "中";
  if (count === 1) return "低";
  return "";
}

function confidenceFromCoverageCount(count) {
  if (count >= 3) return "高";
  if (count === 2) return "中";
  if (count === 1) return "低";
  return "";
}

function songArtistTarget(item) {
  return item.primary_artist_name || item.artist_name || item.display_artist_name || "";
}

function dataDate() {
  return state.dashboard?.score_date || state.dashboard?.chart_date || "--";
}

function setUpdateTime(value) {
  const node = $("#updateTime");
  if (node) node.textContent = `更新时间：${value || dataDate()}`;
}

function setPageMeta(title, eyebrow, subtitle) {
  $("#pageTitle").textContent = title;
  $("#pageEyebrow").textContent = eyebrow;
  $("#pageSubtitle").textContent = subtitle;
}

function buttonArrow(text) {
  return `${escapeHtml(text)} →`;
}

function limitFor(key) {
  return state.expanded[key] ? 50 : 10;
}

function coverHtml(url, text, className = "cover") {
  const safeText = escapeHtml((text || "音").slice(0, 1));
  if (url) {
    return `<div class="${className}"><img src="${escapeHtml(url)}" alt="${escapeHtml(text || "封面")}" loading="lazy" /></div>`;
  }
  return `<div class="${className}">${safeText}</div>`;
}

function thumbHtml(url, text, className = "item-cover") {
  const safeText = escapeHtml((text || "音").slice(0, 1));
  if (url) {
    return `<span class="${className}"><img src="${escapeHtml(url)}" alt="${escapeHtml(text || "封面")}" loading="lazy" /></span>`;
  }
  return `<span class="${className}">${safeText}</span>`;
}

function tagForSong(song) {
  const joined = `${song.song_name || ""} ${song.album_name || ""} ${song.artist_name || ""}`.toLowerCase();
  if (/rap|hip|说唱|rapper|flow/i.test(joined)) return styleDefForName("说唱 / Hip-Hop");
  if (/r&b|soul|blue|jazz/i.test(joined)) return styleDefForName("R&B / Soul");
  if (/国风|古风|山河|江湖|戏腔|梦/.test(joined)) return styleDefForName("国风 / 古风");
  if (/ost|影视|剧|theme|片尾|电影|国乐/.test(joined)) return styleDefForName("OST / 影视音乐");
  if (/dj|电音|电子|dance|edm|remix|club/i.test(joined)) return styleDefForName("电子 / Dance");
  if (/rock|摇滚|乐队|guitar/i.test(joined)) return styleDefForName("摇滚");
  if (/民谣|木吉他|远方|故乡|城市/.test(joined)) return styleDefForName("民谣");
  if (/acg|动漫|游戏|二次元|初音/i.test(joined)) return styleDefForName("ACG / 二次元");
  if (/古典|classical|钢琴|交响/i.test(joined)) return styleDefForName("古典");
  if (/短视频|抖音|快手|tiktok/i.test(joined)) return styleDefForName("短视频热歌");
  return styleDefForName("流行");
}

function normalizeStyleName(styleName) {
  const text = String(styleName || "").trim();
  const lower = text.toLowerCase().replace(/\s+/g, "");
  if (!text) return null;
  if (/^(其他|其他榜|未分类|未识别|unknown|misc|other)$/i.test(text)) return null;
  if (/热歌榜|新歌榜|飙升榜|综合榜|top\s*500|热门歌曲|评论热度榜|平台总榜/i.test(text)) return null;
  if (/说唱|嘻哈|hip-?hop|rap/i.test(text)) return "说唱 / Hip-Hop";
  if (/r&b|soul|节奏布鲁斯/i.test(text)) return "R&B / Soul";
  if (/国风|古风|中国风/.test(text)) return "国风 / 古风";
  if (/ost|影视|原声|剧集|电影/i.test(text)) return "OST / 影视音乐";
  if (/电子|dance|edm|electro|dj|电音/i.test(text)) return "电子 / Dance";
  if (/摇滚|rock/i.test(text)) return "摇滚";
  if (/民谣|folk/i.test(text)) return "民谣";
  if (/acg|二次元|动漫|动画|游戏/i.test(text)) return "ACG / 二次元";
  if (/古典|classical/i.test(text)) return "古典";
  if (/短视频|抖音|快手|tiktok/i.test(text)) return "短视频热歌";
  if (/^(pop|c-pop|cpop|mandopop|mandarinpop|流行|流行榜)$/.test(lower) || /华语流行|国语流行|中文流行|mandarin\s*pop|c-?pop|流行\/pop|pop\/流行/i.test(text)) return "流行";
  return null;
}

function styleDefForName(styleName, index = 0) {
  return STYLE_DEFS.find((style) => style.name === styleName) || STYLE_DEFS[index % STYLE_DEFS.length];
}

function songRankMetaText(item) {
  const parts = [];
  const heat = item.adjusted_heat || item.adjustedHeat || item.heat_score || item.avg_heat_score;
  if (heat) parts.push(`综合热度：${formatNumber(heat)}`);
  const sourceNames = item.source_platform_names || item.platform_names || [];
  if (sourceNames.length && sourceNames.length <= 3) {
    parts.push(`来源：${sourceNames.join("、")}`);
  } else if (item.dominant_platform_name || item.dominant_platform) {
    parts.push(`主导平台：${item.dominant_platform_name || item.dominant_platform}`);
  }
  return parts.join(" ｜ ");
}

function songDisplayName(item) {
  return item.display_song_name || item.song_name || "--";
}

function songLinkHtml(item, songName = songDisplayName(item)) {
  return `<button class="song-link" type="button" data-song-id="${item.song_id || ""}">${escapeHtml(songName)}</button>`;
}

function artistLinkHtml(artistTarget, artistName) {
  return `<button class="artist-link" type="button" data-artist="${escapeHtml(artistTarget || "")}">${escapeHtml(artistName || "--")}</button>`;
}

function songRankMainHtml(item, metaText = "") {
  const artistTarget = item.primary_artist_name || item.artist_name || "";
  return `
    <div class="rank-main">
      ${thumbHtml(item.cover_url, item.song_name)}
      <div>
        ${songLinkHtml(item, item.song_name || "--")}
        <div class="rank-meta">
          ${artistLinkHtml(artistTarget, item.display_artist_name || item.artist_name || "--")}
          ${metaText ? ` ｜ ${escapeHtml(metaText)}` : ""}
        </div>
      </div>
    </div>
  `;
}

function tableIdentityHtml({ thumb, content }) {
  return `
    <div class="table-identity">
      ${thumb}
      ${content}
    </div>
  `;
}

function songRankRow(item, rank = item.rank) {
  const metaText = songRankMetaText(item);
  return `
    <div class="rank-row basic">
      <span class="rank-no">${rank || ""}</span>
      ${songRankMainHtml(item, metaText)}
    </div>
  `;
}

function artistRow(item) {
  return `
    <button class="artist-pill artist-basic" type="button" data-artist="${escapeHtml(item.artist_name || "")}">
      <span class="rank-no">${item.rank || ""}</span>
      ${thumbHtml(item.artist_avatar_url, item.artist_name, "item-cover avatar-thumb")}
      <b>${escapeHtml(item.artist_name || "--")}</b>
    </button>
  `;
}

function riseReason(item) {
  if ((item.rank_delta || 0) > 10) return "排名跃升";
  if ((item.comment_count || 0) > 10000) return "评论暴涨";
  if ((item.heat_score || 0) > 45) return "热度增长";
  if (/new|新/i.test(item.chart_type || item.trend_label || "")) return "新增入榜";
  if (/ost|影视|剧/.test(`${item.song_name || ""}${item.album_name || ""}`)) return "OST带动";
  if ((item.rank_delta || 0) > 0) return "歌手热度带动";
  return item.trend_label || "平台推荐";
}

function risingRow(item) {
  const growth = item.rank_delta ? `+${item.rank_delta}` : "新增";
  return `
    <div class="trend-row">
      <span class="rank-no">${item.rank || ""}</span>
      ${songRankMainHtml(item)}
      <span class="growth">${growth}</span>
      <span class="tag">${escapeHtml(riseReason(item))}</span>
    </div>
  `;
}

function taggedSongRow(item, tag) {
  return `
    <div class="trend-row simple">
      <span class="rank-no">${item.rank || ""}</span>
      ${songRankMainHtml(item)}
      <span class="tag">${escapeHtml(tag)}</span>
    </div>
  `;
}

function songTitleCell(item) {
  const songName = songDisplayName(item);
  const artistTarget = songArtistTarget(item);
  return tableIdentityHtml({
    thumb: thumbHtml(item.cover_url, songName),
    content: `
      <div>
        ${songLinkHtml(item, songName)}
        <div class="rank-meta">
          ${artistLinkHtml(artistTarget, item.display_artist_name || item.artist_name || "--")}
        </div>
      </div>
    `,
  });
}

function rankingTable(items, limit = 5) {
  const rows = items.slice(0, limit).map((item, index) => {
    return `
      <tr>
        <td><span class="rank-no">${item.rank || index + 1}</span></td>
        <td>${songTitleCell(item)}</td>
        <td><b>${formatNumber(heatValue(item))}</b></td>
      </tr>
    `;
  }).join("");
  return `
    <div class="table-wrap">
      <table class="table data-table">
        <thead>
          <tr>
            <th>排名</th>
            <th>歌曲 / 歌手</th>
            <th>综合热度</th>
          </tr>
        </thead>
        <tbody>${rows || `<tr><td colspan="3">${emptyText("暂无榜单数据")}</td></tr>`}</tbody>
      </table>
    </div>
  `;
}

function miniRankingList(items, tagResolver, limit = 5) {
  return items.slice(0, limit).map((item, index) => {
    const tag = typeof tagResolver === "function" ? tagResolver(item) : tagResolver;
    return `
      <div class="mini-rank-card">
        <span class="rank-no">${item.rank || index + 1}</span>
        ${songTitleCell(item)}
        ${tag ? `<span class="tag">${escapeHtml(tag)}</span>` : ""}
      </div>
    `;
  }).join("") || emptyText("暂无榜单数据");
}

function artistField(item, keys) {
  for (const key of keys) {
    const value = item?.[key];
    if (Array.isArray(value) && value.length) return value.join("、");
    if (value != null && value !== "") return value;
  }
  return "";
}

function renderArtistRankingItem(item, index) {
  const rank = item.rank || index + 1;
  const artistName = artistField(item, ["artist_name", "name"]) || "--";
  const avatar = artistField(item, ["artist_avatar_url", "artist_avatar", "avatar", "cover_url"]);
  const songCount = artistField(item, ["chart_song_count", "song_count"]);
  const avgHeat = artistField(item, ["avg_heat_score", "avg_heat", "heat_score", "artist_heat_score", "total_score"]);
  const representativeSong = artistField(item, ["representative_song", "representative_songs"]);
  const rankClass = rank <= 3 ? `top-${rank}` : "";
  const metaParts = [];
  if (songCount) metaParts.push(`上榜歌曲：${formatNumber(songCount)} 首`);
  if (avgHeat) metaParts.push(`平均热度：${formatNumber(avgHeat)}`);
  if (representativeSong) metaParts.push(`代表歌曲：${representativeSong}`);
  return `
    <button class="artist-rank-item" type="button" data-artist="${escapeHtml(artistName)}">
      <span class="rank-no ${rankClass}">${rank}</span>
      ${thumbHtml(avatar, artistName, "item-cover avatar-thumb")}
      <span class="artist-rank-copy">
        <b>${escapeHtml(artistName)}</b>
        ${metaParts.length ? `<small>${escapeHtml(metaParts.join(" · "))}</small>` : ""}
      </span>
      <span class="artist-rank-stats">
        ${songCount ? `<small>上榜歌曲</small><b>${formatNumber(songCount)}</b>` : ""}
      </span>
      <span class="artist-rank-stats heat">
        ${avgHeat ? `<small>平均热度</small><b>${formatNumber(avgHeat)}</b>` : ""}
      </span>
      <span class="artist-rank-arrow">→</span>
    </button>
  `;
}

function renderArtistRankingList(items) {
  return `
    <div class="artist-ranking-list">
      ${items.slice(0, 10).map(renderArtistRankingItem).join("") || emptyText("暂无歌手榜数据")}
    </div>
  `;
}

function renderDashboard() {
  $("#dailyHotList").innerHTML = rankingTable(state.daily, 5);
  $("#weeklyMessage").textContent = state.weeklyMessage || "";
  $("#weeklyHotList").innerHTML = rankingTable(state.weekly, 5);
  $("#artistRankList").innerHTML = renderArtistRankingList(state.artists);
  $("#risingList").innerHTML = miniRankingList(state.rising, riseReason, 5);
  $("#newSongList").innerHTML = miniRankingList(state.newSongs, "", 5);
  $("#interactionHeatList").innerHTML = miniRankingList(state.interactionHeat, "", 5);
  renderTreemap();
}

function emptyText(text) {
  return `<p class="muted empty">${escapeHtml(text)}</p>`;
}

function styleWeight(style) {
  return Number(style.songCount || style.song_count || style.songs?.length || 0);
}

function ensureCoreStylesVisible(styleStats, limit = 10) {
  const styles = styleStats.slice().sort((a, b) => styleWeight(b) - styleWeight(a));
  const popIndex = styles.findIndex((style) => style.name === "流行" && styleWeight(style) > 0);
  if (popIndex >= 0 && popIndex >= limit) {
    const [popStyle] = styles.splice(popIndex, 1);
    styles.splice(limit - 1, 0, popStyle);
  }
  return styles;
}

function renderTreemap() {
  const top = ensureCoreStylesVisible(state.styleBuckets, 10).slice(0, 10);
  const total = Number(state.styleMeta?.classifiedSongCount || state.styleMeta?.classified_song_count)
    || state.styleBuckets.reduce((sum, style) => sum + styleWeight(style), 0)
    || 1;
  $("#styleTreemap").innerHTML = top.map((style, index) => {
    const count = styleWeight(style);
    const percent = count / total * 100;
    const sizeClass = index === 0 ? "is-xl" : index < 3 ? "is-lg" : index < 6 ? "is-md" : "is-sm";
    return `
      <button class="tree-cell style-link ${sizeClass}" type="button" data-style="${escapeHtml(style.name)}" style="--tile-color:${style.color}">
        <strong>${escapeHtml(style.name)}</strong>
        <b>${formatPercent(percent)}</b>
        <small>${formatNumber(count)} 首</small>
      </button>
    `;
  }).join("") || emptyText("暂无风格数据");
  const names = top.filter((style) => styleWeight(style) > 0).slice(0, 3).map((style) => style.name).join("、");
  $("#styleSummary").textContent = names ? `风格解读：已识别风格的上榜歌曲主要集中在${names}。` : "风格解读：等待更多明确风格榜单数据形成分布。";
}

function listConfig(key) {
  const configs = {
    daily: { title: "歌曲热度日榜 TOP50", eyebrow: "歌曲热度榜区", items: state.daily, type: "song" },
    weekly: { title: "歌曲热度周榜 TOP50", eyebrow: "歌曲热度榜区", items: state.weekly, type: "song" },
    artists: { title: "热门歌手总榜 TOP50", eyebrow: "热门歌手榜区", items: state.artists, type: "artist" },
    rising: { title: "近期飙升歌曲榜 TOP50", eyebrow: "歌曲动态榜单区", items: state.rising, type: "rising" },
    newSongs: { title: "新歌总榜 TOP50", eyebrow: "歌曲动态榜单区", items: state.newSongs, type: "new" },
    interaction: { title: "互动热度榜 TOP50", eyebrow: "歌曲动态榜单区", items: state.interactionHeat, type: "interaction" },
  };
  return configs[key] || configs.daily;
}

function songCell(item) {
  const songName = songDisplayName(item);
  return tableIdentityHtml({
    thumb: thumbHtml(item.cover_url, songName),
    content: songLinkHtml(item, songName),
  });
}

function artistCell(item) {
  return tableIdentityHtml({
    thumb: thumbHtml(item.artist_avatar_url, item.artist_name, "item-cover avatar-thumb"),
    content: artistLinkHtml(item.artist_name || "", item.artist_name || "--"),
  });
}

function songArtistCell(item) {
  const artistTarget = item.primary_artist_name || item.artist_name || "";
  return tableIdentityHtml({
    thumb: thumbHtml(item.artist_avatar_url, item.artist_name, "item-cover avatar-thumb"),
    content: artistLinkHtml(artistTarget, item.display_artist_name || item.artist_name || "--"),
  });
}

function renderSongListTable(items, options = {}) {
  const includeReason = options.reason;
  const includeGrowth = options.growth;
  const colSpan = 4 + (includeGrowth ? 1 : 0) + (includeReason ? 1 : 0);
  return `
    <table class="table list-table">
      <thead>
        <tr>
          <th>排名</th>
          <th>歌曲</th>
          <th>歌手</th>
          <th>综合热度</th>
          ${includeGrowth ? "<th>增长</th>" : ""}
          ${includeReason ? "<th>原因标签</th>" : ""}
        </tr>
      </thead>
      <tbody>
        ${items.slice(0, 50).map((item, index) => `
          <tr>
            <td>${item.rank || index + 1}</td>
            <td>${songCell(item)}</td>
            <td>${songArtistCell(item)}</td>
            <td>${formatNumber(heatValue(item))}</td>
            ${includeGrowth ? `<td><span class="growth">${item.rank_delta ? `+${item.rank_delta}` : "新增"}</span></td>` : ""}
            ${includeReason ? `<td><span class="tag">${escapeHtml(reasonText(item, includeReason))}</span></td>` : ""}
          </tr>
        `).join("") || `<tr><td colspan="${colSpan}">暂无榜单数据</td></tr>`}
      </tbody>
    </table>
  `;
}

function reasonText(item) {
  return riseReason(item);
}

function renderArtistListTable(items) {
  return `
    <table class="table list-table">
      <thead><tr><th>排名</th><th>歌手</th><th>歌手热度分</th><th>最佳平台排名</th></tr></thead>
      <tbody>
        ${items.slice(0, 50).map((item, index) => `
          <tr>
            <td>${item.rank || index + 1}</td>
            <td>${artistCell(item)}</td>
            <td>${formatNumber(item.artist_heat_score || item.total_score)}</td>
            <td>${item.best_artist_chart_rank || "--"}</td>
          </tr>
        `).join("") || `<tr><td colspan="4">暂无歌手榜数据</td></tr>`}
      </tbody>
    </table>
  `;
}

function openList(key) {
  const config = listConfig(key);
  state.activeList = key;
  switchView("list");
  $("#listEyebrow").textContent = config.eyebrow;
  $("#listTitle").textContent = config.title;
  if (config.type === "artist") {
    $("#listContent").innerHTML = renderArtistListTable(config.items);
  } else if (config.type === "rising") {
    $("#listContent").innerHTML = renderSongListTable(config.items, { growth: true, reason: true });
  } else {
    $("#listContent").innerHTML = renderSongListTable(config.items);
  }
}

function renderStyleCenter() {
  const totalSongs = Number(state.styleMeta?.classifiedSongCount || state.styleMeta?.classified_song_count)
    || state.styleBuckets.reduce((sum, style) => sum + Number(style.songCount || style.songs?.length || 0), 0);
  $("#styleCards").innerHTML = state.styleBuckets.map((style) => {
    const songs = style.songs.slice(0, 3);
    const firstCover = songs.find((song) => song.cover_url)?.cover_url;
    const total = Math.max(totalSongs, 1);
    const percent = Number(style.songCount || style.songs?.length || 0) / total * 100;
    return `
      <button class="style-card" type="button" data-style="${escapeHtml(style.name)}">
        <div class="style-cover" style="background:${style.color}">
          ${firstCover ? `<img src="${escapeHtml(firstCover)}" alt="${escapeHtml(style.name)}" loading="lazy" />` : ""}
        </div>
        <div class="style-card-body">
          <span class="card-arrow">›</span>
          <h3>${escapeHtml(style.name)}</h3>
          <small class="rank-meta">更新：${state.dashboard?.score_date || state.dashboard?.chart_date || "--"} · ${formatNumber(style.songCount || style.songs.length)} 首</small>
          <ol>
            ${songs.length ? songs.map((song, index) => `<li>${index + 1}. ${escapeHtml(song.song_name)} - ${escapeHtml(song.artist_name)}</li>`).join("") : "<li>等待榜单数据</li>"}
          </ol>
          <span class="tag">占比 ${formatPercent(percent)}</span>
        </div>
      </button>
    `;
  }).join("") || emptyText("暂无风格榜单数据");
}

function showStyleDetail(styleName) {
  const style = state.styleBuckets.find((item) => item.name === styleName);
  if (!style) return;
  state.activeStyle = styleName;
  $("#styleCards").classList.add("hidden");
  $("#styleDetail").classList.remove("hidden");
  $("#backToStyles").classList.remove("hidden");
  const firstCover = style.songs.find((song) => song.cover_url)?.cover_url;
  const songs = style.songs.slice(0, state.expanded.style ? 50 : 10);
  $("#styleDetail").innerHTML = `
    <article class="hero-card">
      ${coverHtml(firstCover, style.name)}
      <div>
        <p class="eyebrow">风格详情页</p>
        <h2>${escapeHtml(style.name)}榜</h2>
        <p class="muted">${escapeHtml(style.desc)}</p>
        <div class="tag-row">${style.tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
      </div>
      <button class="ghost-button" type="button" data-expand="style">${state.expanded.style ? "收起" : "查看更多"}</button>
    </article>
    <section class="detail-grid single">
      <article class="panel">
        <div class="panel-head"><h2>当前风格歌曲热度榜</h2><span>${state.expanded.style ? "TOP50" : "TOP10"}</span></div>
        <table class="table">
          <thead><tr><th>排名</th><th>歌曲</th><th>歌手</th></tr></thead>
          <tbody>${songs.map((song, index) => `
            <tr>
              <td>${index + 1}</td>
              <td>${songCell(song)}</td>
              <td>${songArtistCell(song)}</td>
            </tr>
          `).join("") || `<tr><td colspan="3">暂无歌曲数据</td></tr>`}</tbody>
        </table>
      </article>
    </section>
  `;
}

function switchView(view) {
  if (state.activeView === "explore" && view !== "explore") {
    cleanupExploreSession(true);
  }
  state.activeView = view;
  document.querySelectorAll(".view").forEach((node) => node.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  const metas = {
    dashboard: ["三大音乐平台歌曲热度分析系统"],
    list: ["完整榜单", "TOP50", "查看完整榜单数据"],
    styles: ["风格榜单中心", "STYLE CENTER", "从音乐风格维度观察歌曲流行趋势"],
    explore: ["歌曲探索 ", "SONG EXPLORER", "实时查询三大平台，分析任意歌曲的当前热度"],
    crossPlatform: ["跨平台热度重合分析", "CROSS PLATFORM", "分析三大平台公开榜单的重合度与覆盖情况"],
    song: ["歌曲详情分析页", "歌曲详情", "单曲综合热度、平台表现与趋势分析"],
    artist: ["歌手详情分析页", "歌手详情", "歌手跨平台表现、代表歌曲与趋势分析"],
  };
  $(`#${view}View`)?.classList.add("active");
  const meta = metas[view] || ["分析详情", "Music Hot Analysis", ""];
  setPageMeta(meta[0], meta[1], meta[2]);
}

function platformValues(score) {
  const values = MAIN_PLATFORMS.map((platform) => ({
    ...platform,
    value: Number(score?.[`${platform.code}_score`] || 0),
  }));
  const total = values.reduce((sum, item) => sum + item.value, 0) || 1;
  return values.map((item) => ({ ...item, percent: Math.round((item.value / total) * 100) }));
}

function platformPerformanceItems(platformPerformance) {
  if (Array.isArray(platformPerformance)) return platformPerformance;
  if (Array.isArray(platformPerformance?.platforms)) return platformPerformance.platforms;
  if (Array.isArray(platformPerformance?.platform_performance)) return platformPerformance.platform_performance;
  if (Array.isArray(platformPerformance?.platformPerformance)) return platformPerformance.platformPerformance;
  return [];
}

function isEnteredPlatform(item) {
  return Boolean(
    item?.entered_chart
    || item?.enteredChart
    || item?.in_current_chart
    || item?.inCurrentChart
    || item?.rank != null
  );
}

function platformHeatValue(item) {
  const heat = Number(item?.platform_heat_score ?? item?.platformHeatScore ?? item?.heat_score ?? item?.heatScore);
  if (heat > 0) return heat;
  const rankScore = Number(item?.rank_score ?? item?.rankScore);
  return rankScore > 0 ? rankScore : 0;
}

function getEnteredPlatforms(platformPerformance) {
  return platformPerformanceItems(platformPerformance)
    .filter(isEnteredPlatform)
    .map((item) => platformCode(item.platform || item.platform_name || item.name));
}

function computePlatformHeatShares(platformPerformance) {
  const rows = platformPerformanceItems(platformPerformance);
  const enteredCodes = new Set(getEnteredPlatforms(rows));
  const heatByPlatform = new Map();
  rows.forEach((item) => {
    const code = platformCode(item.platform || item.platform_name || item.name);
    if (!enteredCodes.has(code)) return;
    const heat = platformHeatValue(item);
    if (heat > 0) heatByPlatform.set(code, (heatByPlatform.get(code) || 0) + heat);
  });
  const total = [...heatByPlatform.values()].reduce((sum, value) => sum + value, 0);
  return MAIN_PLATFORMS.map((platform) => {
    const heat = heatByPlatform.get(platform.code) || 0;
    return {
      ...platform,
      value: heat,
      entered: enteredCodes.has(platform.code),
      percent: total > 0 && heat > 0 ? Math.round((heat / total) * 100) : 0,
    };
  });
}

function computeSongCoverageFromPlatformPerformance(platformPerformance) {
  const values = computePlatformHeatShares(platformPerformance);
  const coverageCountValue = new Set(getEnteredPlatforms(platformPerformance).filter((code) => (
    MAIN_PLATFORMS.some((platform) => platform.code === code)
  ))).size;
  const dominant = values.slice().sort((a, b) => b.percent - a.percent || b.value - a.value)[0];
  return {
    coverageCount: coverageCountValue,
    coverageText: coverageCountValue ? `${coverageCountValue}/3` : "",
    dominantPlatform: dominant?.percent > 0 ? dominant.name : "",
    values,
  };
}

function performanceFromScore(score) {
  return {
    platforms: MAIN_PLATFORMS.map((platform) => {
      const heat = Number(score?.[`${platform.code}_score`] || 0);
      return {
        platform: platform.code,
        platform_name: platform.name,
        rank: heat > 0 ? score?.rank : null,
        rank_score: heat || null,
        heat_score: heat || null,
        in_current_chart: heat > 0,
      };
    }),
  };
}

function pieHtml(values) {
  const first = values[0]?.percent ?? 33;
  const second = first + (values[1]?.percent ?? 33);
  return `
    <div class="pie-chart-wrap">
      <div class="pie" style="--a:${first}%; --b:${second}%"></div>
      <div class="legend">
        ${values.map((item) => `<span><i class="dot" style="background:${item.color}"></i>${escapeHtml(item.name)} ${item.percent}%</span>`).join("")}
      </div>
    </div>
  `;
}

function lineChart(points, valueKey = "heat_score") {
  const data = points.length ? points : [{ score_date: "--", [valueKey]: 0 }];
  const width = 680;
  const height = 220;
  const values = data.map((item) => Number(item[valueKey] || item.heat_score || 0));
  const max = Math.max(...values, 1);
  const step = data.length > 1 ? width / (data.length - 1) : width;
  const coords = data.map((item, index) => {
    const x = data.length > 1 ? index * step : width / 2;
    const y = height - (Number(item[valueKey] || item.heat_score || 0) / max) * 170 - 26;
    return [x, y];
  });
  const path = coords.map(([x, y], index) => `${index ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  return `
    <div class="line-chart">
      <svg viewBox="0 0 ${width} ${height}" role="img">
        <line x1="0" y1="194" x2="${width}" y2="194" stroke="#d8e0e5" />
        <path d="${path}" fill="none" stroke="#0f7a6c" stroke-width="4" stroke-linecap="round" />
        ${coords.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5" fill="#d6542a" />`).join("")}
      </svg>
    </div>
  `;
}

function horizontalBars(items, options = {}) {
  const labelKey = options.labelKey || "name";
  const valueKey = options.valueKey || "value";
  const suffix = options.suffix || "";
  const max = Math.max(...items.map((item) => Number(item[valueKey] || 0)), 1);
  return `
    <div class="bar-list">
      ${items.map((item) => {
        const value = Number(item[valueKey] || 0);
        const label = typeof labelKey === "function" ? labelKey(item) : item[labelKey];
        return `
          <div class="bar-row">
            <span>${escapeHtml(label || "--")}</span>
            <i style="width:${Math.max(4, (value / max) * 100)}%"></i>
            <b>${formatNumber(value)}${suffix}</b>
          </div>
        `;
      }).join("") || emptyText("暂无数据")}
    </div>
  `;
}

function multiLineChart(series, xAxis) {
  const width = 680;
  const height = 240;
  const colors = ["#0f7a6c", "#d6542a", "#2b6cb0", "#d6a11d"];
  const values = series.flatMap((item) => item.data || []).map(Number);
  const max = Math.max(...values, 1);
  const labels = xAxis && xAxis.length ? xAxis : ["Top10", "Top20", "Top50"];
  const step = labels.length > 1 ? width / (labels.length - 1) : width;
  const paths = series.map((item, seriesIndex) => {
    const coords = (item.data || []).map((value, index) => {
      const x = labels.length > 1 ? index * step : width / 2;
      const y = height - (Number(value || 0) / max) * 170 - 34;
      return [x, y];
    });
    const path = coords.map(([x, y], index) => `${index ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    const color = colors[seriesIndex % colors.length];
    return `
      <path d="${path}" fill="none" stroke="${color}" stroke-width="4" stroke-linecap="round" />
      ${coords.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5" fill="${color}" />`).join("")}
    `;
  }).join("");
  return `
    <div class="line-chart">
      <svg viewBox="0 0 ${width} ${height}" role="img">
        <line x1="0" y1="${height - 34}" x2="${width}" y2="${height - 34}" stroke="#d8e0e5" />
        ${labels.map((label, index) => {
          const x = labels.length > 1 ? index * step : width / 2;
          return `<text x="${x}" y="${height - 8}" text-anchor="middle" fill="#67727e" font-size="12">${escapeHtml(label)}</text>`;
        }).join("")}
        ${paths}
      </svg>
      <div class="legend">
        ${series.map((item, index) => `<span><i class="dot" style="background:${colors[index % colors.length]}"></i>${escapeHtml(item.name)}</span>`).join("")}
      </div>
    </div>
  `;
}

function songTrendStats(points) {
  const values = (points || []).map((item) => Number(item.heat_score || 0)).filter((value) => Number.isFinite(value));
  if (!values.length) {
    return { max: 0, min: 0, change: 0, label: "等待数据" };
  }
  const first = values[0];
  const last = values[values.length - 1];
  const change = last - first;
  let label = "整体稳定";
  if (change > 5) label = "近期上升";
  if (change < -5) label = "近期回落";
  return {
    max: Math.max(...values),
    min: Math.min(...values),
    change,
    label,
  };
}

function trendStatsHtml(stats) {
  return `
    <div class="stat-strip">
      <span><b>${formatNumber(stats.max)}</b><small>最高热度</small></span>
      <span><b>${formatNumber(stats.min)}</b><small>最低热度</small></span>
      <span><b>${stats.change >= 0 ? "+" : ""}${formatNumber(stats.change)}</b><small>区间变化</small></span>
      <span><b>${escapeHtml(stats.label)}</b><small>趋势判断</small></span>
    </div>
  `;
}

function scoreBreakdownHtml(data) {
  const blocked = /播放|收藏|play|collect|favorite/i;
  const items = (data?.items || []).filter((item) => !blocked.test(`${item.key || ""}${item.name || ""}`));
  return `
    <div class="score-layout">
      <div class="score-ring" style="--score:${Math.min(Number(data?.final_heat_score || 0), 100)}%">
        <strong>${formatNumber(data?.final_heat_score)}</strong>
        <small>综合热度</small>
      </div>
      <div>
        <b>热度分数构成</b>
        <p class="muted">覆盖平台：${Number(data?.platform_count || 0) > 0 ? `${formatNumber(data?.platform_count)}/3` : "--"} · 可信度：${escapeHtml(data?.confidence_label || "--")}</p>
      </div>
    </div>
    <div class="score-bars">
      ${items.map((item) => `
        <div class="score-bar ${item.missing ? "is-missing" : ""}">
          <div>
            <span>${escapeHtml(item.name)}</span>
            <b>${item.value == null ? "--" : formatNumber(item.value)}</b>
          </div>
          <i style="width:${Math.max(4, Math.min(Number(item.value || 0), 100))}%"></i>
          <small>${escapeHtml(item.description || "")}</small>
        </div>
      `).join("") || emptyText("暂无分数构成数据")}
    </div>
  `;
}

function summaryMetric(label, value, suffix = "") {
  return `<span><b>${formatNumber(value)}</b><small>${escapeHtml(label)}${suffix}</small></span>`;
}

function coverageDistributionHtml(items) {
  return `
    <div class="bar-list">
      ${items.map((item) => `
        <div class="bar-row">
          <span>${escapeHtml(item.label)}</span>
          <i style="width:${Math.max(4, Number(item.song_count || 0) / Math.max(...items.map((row) => Number(row.song_count || 0)), 1) * 100)}%"></i>
          <b>${formatNumber(item.song_count)} 首</b>
        </div>
      `).join("") || emptyText("暂无覆盖分布数据")}
    </div>
  `;
}

function commonSongsSummaryHtml(summary) {
  const samples = summary?.sample_common_songs || [];
  return `
    <div class="stat-strip">
      ${summaryMetric("三平台共同上榜", summary?.three_platform_count || 0)}
      ${summaryMetric("双平台共同上榜", summary?.two_platform_count || 0)}
      ${summaryMetric("单平台上榜", summary?.one_platform_count || 0)}
      ${summaryMetric("共同歌曲平均热度", summary?.three_platform_avg_heat || 0)}
      ${summaryMetric("共同歌曲平均排名", summary?.three_platform_avg_rank || 0)}
    </div>
    <table class="table list-table">
      <thead><tr><th>示例歌曲</th><th>歌手</th><th>平均排名</th><th>综合热度</th></tr></thead>
      <tbody>
        ${samples.map((item) => `
          <tr>
            <td>${escapeHtml(item.song_name)}</td>
            <td>${escapeHtml(item.artist_name)}</td>
            <td>${formatNumber(item.avg_rank)}</td>
            <td>${formatNumber(item.heat_score)}</td>
          </tr>
        `).join("") || `<tr><td colspan="4">暂无三平台共同上榜歌曲</td></tr>`}
      </tbody>
    </table>
  `;
}

function pairwiseOverlapCards(items) {
  return `
    <div class="pair-grid">
      ${items.map((item) => {
        const platforms = item.platforms || String(item.pair || "").split(/\s*[-/vs]+\s*/);
        return `
          <div class="pair-card">
            <div class="pair-platforms">
              ${platformBadges(platforms)}
              <span>${escapeHtml(item.pair || platforms.map(platformName).join(" vs "))}</span>
            </div>
            <strong>${formatPercent(item.jaccard)}</strong>
            <p class="muted">共同歌曲 ${formatNumber(item.intersection_count || 0)} 首 / 并集歌曲 ${formatNumber(item.union_count || 0)} 首</p>
            <i style="width:${Math.max(4, Number(item.jaccard || 0))}%"></i>
          </div>
        `;
      }).join("") || emptyText("暂无平台重合数据")}
    </div>
  `;
}

function crossPlatformInsights(data) {
  const similarity = data.similarity?.items || [];
  const coverage = data.coverage?.items || [];
  const common = data.common || {};
  const topPair = similarity.slice().sort((a, b) => Number(b.jaccard || 0) - Number(a.jaccard || 0))[0];
  const total = Number(common.total_canonical_songs || coverage.reduce((sum, item) => sum + Number(item.song_count || 0), 0));
  const single = coverage.find((item) => Number(item.coverage_count) === 1)?.song_count || common.one_platform_count || 0;
  const insights = [];
  if (topPair) insights.push(`${topPair.pair} 的重合度最高，达到 ${formatPercent(topPair.jaccard)}。`);
  if (total) insights.push(`本次样本共覆盖 ${formatNumber(total)} 首去重歌曲，三平台共同上榜 ${formatNumber(common.three_platform_count || 0)} 首。`);
  if (single) insights.push(`单平台上榜歌曲 ${formatNumber(single)} 首，说明平台内容差异仍然明显。`);
  if (Number(common.three_platform_avg_heat || 0) > 0) insights.push(`三平台共同歌曲平均热度为 ${formatNumber(common.three_platform_avg_heat)}，可作为核心热门池观察。`);
  return insights.length ? insights : ["等待跨平台接口返回更多数据后生成观察。"];
}

function renderCrossPlatformAnalysis() {
  const data = state.crossPlatform || {};
  const counts = data.counts?.items || [];
  const similarity = data.similarity?.items || [];
  const coverage = data.coverage?.items || [];
  const common = data.common || {};
  const totalSongs = Number(common.total_canonical_songs || coverage.reduce((sum, item) => sum + Number(item.song_count || 0), 0) || counts.reduce((sum, item) => sum + Number(item.song_count || 0), 0));
  const maxPair = similarity.slice().sort((a, b) => Number(b.jaccard || 0) - Number(a.jaccard || 0))[0] || {};
  const date = data.counts?.chart_date || data.overlap?.chart_date || data.common?.chart_date || "--";
  const dateNode = $("#crossPlatformDate");
  if (dateNode) dateNode.textContent = `数据日期：${date}`;
  $("#crossPlatformContent").innerHTML = `
    <section class="metric-grid">
      <article class="metric-card">
        <span class="metric-icon green">♪</span>
        <div><small>本次采集歌曲数</small><strong>${formatNumber(totalSongs)}</strong><p>覆盖三大平台公开榜单</p></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon blue">%</span>
        <div><small>两两最高重合度</small><strong>${formatPercent(maxPair.jaccard)}</strong><p>${escapeHtml(maxPair.pair || "--")}</p></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon purple">3</span>
        <div><small>三平台共同上榜</small><strong>${formatNumber(common.three_platform_count || 0)}</strong><p>占全部歌曲 ${totalSongs ? formatPercent((common.three_platform_count || 0) / totalSongs * 100) : "--"}</p></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon orange">H</span>
        <div><small>共同歌曲平均热度</small><strong>${formatNumber(common.three_platform_avg_heat || 0)}</strong><p>综合热度 0-100</p></div>
      </article>
    </section>

    <article class="panel">
      <div class="panel-head"><div><h2>两两平台重合度（Jaccard）</h2><p class="muted">重合度 = 共同歌曲数 / 并集歌曲数，仅基于本次公开榜单采集结果。</p></div></div>
      ${pairwiseOverlapCards(similarity)}
    </article>

    <article class="panel">
      <div class="panel-head"><h2>Top N 重合率趋势</h2><span>Top10 / Top20 / Top50</span></div>
      ${multiLineChart(data.overlap?.series || [], data.overlap?.x_axis || [])}
    </article>

    <section class="three-column cross-bottom">
      <article class="panel">
        <div class="panel-head"><h2>歌曲覆盖平台分布</h2><span>1/2/3 平台</span></div>
        ${coverageDistributionHtml(coverage)}
      </article>
      <article class="panel">
        <div class="panel-head"><h2>三平台共同上榜概览</h2><span>${escapeHtml(date)}</span></div>
        ${commonSongsSummaryHtml(common)}
      </article>
      <article class="panel ai-card">
        <div class="panel-head"><h2>AI 观察</h2><span>基于接口数据</span></div>
        <ul class="insight-list">${crossPlatformInsights(data).slice(0, 4).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </article>
    </section>
  `;
}

function explorerInitialHtml() {
  return `
    <article class="panel explorer-empty">
      <p class="muted">输入任意歌曲名或“歌曲 歌手”，开始实时分析。</p>
      <div class="tag-row">
        ${["晴天", "晴天 周杰伦", "有何不可", "修炼爱情 林俊杰"].map((item) => (
          `<button class="tag explore-example" type="button" data-explore-keyword="${escapeHtml(item)}">${escapeHtml(item)}</button>`
        )).join("")}
      </div>
    </article>
  `;
}

function renderSongExplorer(content = "") {
  const node = $("#exploreContent");
  if (node) node.innerHTML = content || explorerInitialHtml();
}

function aiSongSearchLoadingHtml() {
  return `
    <div class="ai-song-loading">
      <span></span>
      <b>AI 正在理解你的描述并检索歌曲...</b>
    </div>
  `;
}

function renderAiSongSearchResults(data) {
  const node = $("#aiSongSearchResults");
  if (!node) return;
  const songs = Array.isArray(data?.songs) ? data.songs : [];
  if (!songs.length) {
    node.innerHTML = `<p class="ai-song-empty">未找到符合条件的歌曲，请尝试其他描述。</p>`;
    return;
  }
  node.innerHTML = `
    <div class="ai-song-result-head">
      <span>识别意图：<b>${escapeHtml(data.intent || "--")}</b></span>
      <small>按综合热度降序推荐 ${songs.length} 首</small>
    </div>
    <div class="ai-song-grid">
      ${songs.map((song) => {
        const chartText = song.chart_name || (Array.isArray(song.charts) && song.charts[0]?.chart_name) || "";
        return `
          <button class="ai-song-card" type="button" data-song-id="${song.song_id || ""}">
            ${thumbHtml(song.cover_url, song.song_name, "item-cover")}
            <span class="ai-song-card-copy">
              <b>${escapeHtml(song.song_name || "--")}</b>
              <small>${escapeHtml(song.artist_name || "--")}</small>
              <small>风格：${escapeHtml(song.style || "--")}</small>
              ${chartText ? `<small>榜单：${escapeHtml(chartText)}</small>` : ""}
            </span>
            <span class="ai-song-score">
              <b>${formatNumber(song.heat_score)}</b>
              <small>综合热度</small>
            </span>
            <span class="ai-song-rank">#${formatNumber(song.rank || 0)}</span>
          </button>
        `;
      }).join("")}
    </div>
  `;
}

async function searchAiSongs(query) {
  const node = $("#aiSongSearchResults");
  if (node) node.innerHTML = aiSongSearchLoadingHtml();
  const data = await api("/api/ai/song-search", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
  state.explorer.aiSearch = data;
  renderAiSongSearchResults(data);
}

function explorerPlatforms(result) {
  return Array.isArray(result?.platforms) ? result.platforms : [];
}

function renderExplorerResult(result) {
  const song = result.canonical_song || {};
  const platforms = explorerPlatforms(result);
  const entity = result.entity || {};
  const entityConfidence = Math.round(Number(entity.confidence || 0) * 100);
  $("#exploreContent").innerHTML = `
    <article class="detail-hero explorer-hero">
      ${coverHtml(song.cover_url, song.song_name)}
      <div class="detail-copy">
        <div class="tag-row">
          <span class="tag">实时探索</span>
          ${entity.song_name ? `<span class="tag">AI识别：${escapeHtml(entity.artist_name ? `${entity.artist_name} · ${entity.song_name}` : entity.song_name)}</span>` : ""}
          ${entityConfidence ? `<span class="tag">置信度 ${entityConfidence}%</span>` : ""}
          ${platforms.filter((item) => item.found).map((item) => `<span class="tag">${escapeHtml(item.platform_name)} ✓</span>`).join("")}
        </div>
        <h2>《${escapeHtml(song.song_name || "--")}》</h2>
        <p class="muted">歌手：${escapeHtml(song.artist_name || "--")}</p>
        <div class="meta-grid">
          ${song.album_name ? `<span>专辑：${escapeHtml(song.album_name)}</span>` : ""}
          ${song.release_time ? `<span>发行时间：${escapeHtml(song.release_time)}</span>` : ""}
          <span>覆盖平台：${platforms.filter((item) => item.found).length}/3</span>
        </div>
      </div>
      <div class="score-panel">
        <div class="score-ring" style="--score:${Number(result.heat_score || 0)}%">
          <strong>${formatNumber(result.heat_score)}</strong>
          <small>综合热度</small>
        </div>
      </div>
    </article>

    <section class="three-column explorer-platform-grid">
      ${platforms.map(renderPlatformAnalysis).join("")}
    </section>

    <section class="two-column">
      <article class="panel">
        <div class="panel-head"><h2>评论数对比</h2><span>成功返回评论数的平台</span></div>
        ${renderCommentComparisonChart(platforms)}
      </article>
      <article class="panel">
        <div class="panel-head"><h2>平台偏好分布</h2><span>按评论数占比</span></div>
        ${renderPlatformPreferenceDistribution(platforms)}
      </article>
    </section>

    <article class="panel ai-card">
      <div class="panel-head"><h2>AI 热度变化分析</h2><span>AI生成</span></div>
      <div id="exploreAiBody">${renderAIHeatAnalysisBlock({ status: "loading" })}</div>
    </article>
  `;
  loadExplorerAI(song.song_name, song.artist_name);
}

function renderPlatformAnalysis(item) {
  const charts = Array.isArray(item.charts) ? item.charts : [];
  const lines = [
    `<div><span>状态</span><b>${item.found ? "已找到" : "未找到"}</b></div>`,
    item.comment_count != null ? `<div><span>评论数</span><b>${formatNumber(item.comment_count)}</b></div>` : "",
    item.found ? `<div><span>榜单</span><b>${charts.length ? "已上榜" : "未进入"}</b></div>` : "",
    charts.length ? `<div><span>最高排名</span><b>${formatNumber(Math.min(...charts.map((chart) => Number(chart.rank || 9999))))}</b></div>` : "",
  ].filter(Boolean).join("");
  return `
    <article class="platform-artist-card ${platformCode(item.platform)} explorer-platform-card">
      <div class="platform-card-head">
        ${platformBadge(item.platform)}
        <h3>${escapeHtml(item.platform_name)}</h3>
      </div>
      <div class="metric-lines">${lines}</div>
      ${charts.length ? `<div class="tag-row">${charts.map((chart) => `<span class="tag">${escapeHtml(chart.chart_name)} #${formatNumber(chart.rank)}</span>`).join("")}</div>` : ""}
    </article>
  `;
}

function renderCommentComparisonChart(platforms) {
  const rows = platforms.filter((item) => item.comment_count != null);
  if (!rows.length) return `<p class="muted">仅展示成功返回评论数的平台。</p>`;
  const max = Math.max(...rows.map((item) => Number(item.comment_count || 0)), 1);
  return `
    <div class="bar-list">
      ${rows.map((item) => {
        const value = Number(item.comment_count || 0);
        return `
          <div class="bar-row">
            <span>${escapeHtml(item.platform_name)}</span>
            <i style="width:${Math.max(4, value / max * 100)}%"></i>
            <b>${formatNumber(value)}</b>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function platformPreferenceRows(platforms) {
  return platforms.map((item) => {
    const value = Number(item.comment_count);
    const code = platformCode(item.platform || item.platform_name);
    const meta = {
      netease: { color: "#e53935" },
      qq: { color: "#22c55e" },
      kugou: { color: "#3b82f6" },
    }[code] || { color: "#94a3b8" };
    return {
      code,
      name: item.platform_name || platformName(code),
      value,
      color: meta.color,
    };
  }).filter((item) => Number.isFinite(item.value) && item.value > 0);
}

function renderPlatformPreferenceDistribution(platforms) {
  const rows = platformPreferenceRows(platforms);
  const total = rows.reduce((sum, item) => sum + item.value, 0);
  if (!rows.length || total <= 0) {
    return `<div class="preference-empty">暂无足够数据形成分布偏好</div>`;
  }
  return `
    <div class="preference-card-body">
      <div class="preference-stack" aria-label="平台偏好分布">
        ${rows.map((item) => {
          const percent = item.value / total * 100;
          return `<i style="width:${percent}%; background:${item.color}" title="${escapeHtml(item.name)} ${percent.toFixed(1)}%"></i>`;
        }).join("")}
      </div>
      <div class="preference-list">
        ${rows.map((item) => {
          const percent = item.value / total * 100;
          return `
            <div class="preference-row">
              <span><i style="background:${item.color}"></i>${escapeHtml(item.name)}</span>
              <b>${percent.toFixed(1)}%</b>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

async function searchExploreSong(keyword) {
  renderSongExplorer(`<article class="panel">实时查询三大平台中...</article>`);
  const result = await api(`/api/explore/song/search?keyword=${encodeURIComponent(keyword)}`);
  state.explorer.sessionId = result.session_id || "";
  state.explorer.result = result;
  renderExplorerResult(result);
}

async function loadExplorerAI(songName, artistName) {
  const node = $("#exploreAiBody");
  if (!node || !songName) return;
  try {
    const data = await api(`/api/explore/song/ai-analysis?song_name=${encodeURIComponent(songName)}&artist_name=${encodeURIComponent(artistName || "")}`);
    const analysis = String(data.analysis || "").trim() || "AI分析生成失败，请稍后重试。";
    node.innerHTML = renderAIHeatAnalysisBlock({
      status: analysis === "AI分析生成失败，请稍后重试。" ? "error" : "success",
      analysis,
      error_message: analysis,
    }, "explore");
  } catch (error) {
    console.warn("Explorer AI analysis request failed", error);
    node.innerHTML = renderAIHeatAnalysisBlock({ status: "error", error_message: "AI分析生成失败，请稍后重试。" }, "explore");
  }
}

function retryExploreAI() {
  const song = state.explorer.result?.canonical_song || {};
  loadExplorerAI(song.song_name, song.artist_name);
}

function cleanupExploreSession(keepalive = false) {
  const sessionId = state.explorer.sessionId;
  if (!sessionId) return;
  state.explorer.sessionId = "";
  state.explorer.result = null;
  const path = `/api/explore/session/${encodeURIComponent(sessionId)}`;
  const origin = API_ORIGINS[0] || API_BASE;
  fetch(`${origin}${path}`, { method: "DELETE", keepalive }).catch(() => {});
}

function songStatusLabels(score, style, values) {
  const maxPlatform = values.slice().sort((a, b) => b.percent - a.percent)[0];
  const labels = [
    maxPlatform.percent > 50 ? "平台优势明显" : "三平台均衡",
    score?.trend_label || "榜单观察",
    style.name,
  ];
  return labels;
}

function songPlatformPerformanceHtml(data) {
  const platforms = data?.platforms || [];
  return `
    <div class="platform-artist-grid">
      ${platforms.map((item) => {
        const hasPlatformData = Boolean(item.has_platform_data || item.hasPlatformData);
        return `
          <div class="platform-artist-card ${platformCode(item.platform || item.platform_name)}">
            <div class="platform-card-head">
              ${platformBadge(item.platform || item.platform_name)}
              <h3>${escapeHtml(item.platform_name)}</h3>
              ${item.in_current_chart ? `<span class="tag">已上榜</span>` : hasPlatformData ? `<span class="tag">已采集</span>` : ""}
            </div>
            <div class="metric-lines">
              ${item.in_current_chart ? `
                <span>榜单：${escapeHtml(item.chart_name || "--")}</span>
                <span>排名：${item.rank ? formatNumber(item.rank) : "--"}</span>
                <span>排名得分：${item.rank_score == null ? "--" : formatNumber(item.rank_score)}</span>
                <span>平台热度：${item.heat_score == null ? "--" : formatNumber(item.heat_score)}</span>
                <span>进入本次采集榜单：是</span>
                ${Number(item.comment_count || 0) > 0 ? `<span>评论数：${formatNumber(item.comment_count)}</span>` : ""}
              ` : hasPlatformData ? `
                <span>未进入本次采集榜单</span>
                <span>已补充平台数据：是</span>
                ${Number(item.comment_count || 0) > 0 ? `<span>评论数：${formatNumber(item.comment_count)}</span>` : ""}
                ${item.platform_song_id ? `<span>平台歌曲ID：${escapeHtml(item.platform_song_id)}</span>` : ""}
              ` : `
                <span>未进入本次采集榜单</span>
                <span>暂无补充平台数据</span>
              `}
            </div>
          </div>
        `;
      }).join("") || emptyText("暂无平台表现数据")}
    </div>
  `;
}

function renderSongPlatformHeatSource(platformPerformance) {
  const coverage = computeSongCoverageFromPlatformPerformance(platformPerformance);
  return `
    <div class="heat-source-summary">
      <span>覆盖平台：<b>${escapeHtml(coverage.coverageText || "--")}</b></span>
      ${coverage.dominantPlatform ? `<span>主要来源：<b>${escapeHtml(coverage.dominantPlatform)}</b></span>` : ""}
    </div>
    <div class="chart-box">${pieHtml(coverage.values)}</div>
  `;
}

function artistPlatformPerformanceHtml(data) {
  const platforms = data?.platforms || [];
  return `
    <div class="platform-artist-grid">
      ${platforms.map((item) => `
        <div class="platform-artist-card ${platformCode(item.platform || item.platform_name)}">
          <div class="platform-card-head">
            ${platformBadge(item.platform || item.platform_name)}
            <h3>${escapeHtml(item.platform_name)}</h3>
            ${data?.strongest_platform === item.platform ? `<span class="tag">优势平台</span>` : ""}
          </div>
          <div class="metric-lines">
            <span>上榜歌曲数：${formatNumber(item.song_count || 0)} 首</span>
            <span>最高排名：${item.best_rank == null ? "--" : formatNumber(item.best_rank)}</span>
            <span>平均排名：${item.avg_rank == null ? "--" : formatNumber(item.avg_rank)}</span>
            <span>平均热度：${item.avg_heat_score == null ? "--" : formatNumber(item.avg_heat_score)}</span>
            <span>代表歌曲：${escapeHtml((item.representative_songs || []).join("、") || "--")}</span>
            <span>平台得分：${item.avg_heat_score == null ? "--" : formatNumber(item.avg_heat_score)}</span>
          </div>
        </div>
      `).join("") || emptyText("暂无歌手平台表现数据")}
    </div>
    ${data?.strongest_platform_name ? `<p class="muted">${escapeHtml(data.artist_name)} 当前在 ${escapeHtml(data.strongest_platform_name)} 的榜单表现更强。</p>` : ""}
  `;
}

async function openSong(songId) {
  if (!songId) return;
  switchView("song");
  $("#songDetail").innerHTML = `<article class="panel">加载歌曲详情中...</article>`;
  const data = await api(`/api/songs/${songId}`);
  const song = data.song;
  const score = data.latest_score || {};
  let platformPerformance = data.platform_performance || data.platformPerformance || data.platforms || null;
  let platformPerformanceError = null;
  if (!platformPerformance) {
    try {
      platformPerformance = await api(`/api/songs/${songId}/platform-performance?chart_type=hot`);
    } catch (error) {
      platformPerformanceError = error;
      console.warn("Song platform performance request failed", error);
      platformPerformance = performanceFromScore(score);
    }
  }
  const platformCoverage = computeSongCoverageFromPlatformPerformance(platformPerformance);
  const platformConfidence = confidenceFromCoverageCount(platformCoverage.coverageCount);
  const style = tagForSong({ ...song, heat_score: score.heat_score });
  const values = platformCoverage.values;
  const labels = songStatusLabels(score, style, values);
  const recentTrend = (data.trend || []).slice(-30);
  const trendStats = songTrendStats(recentTrend);
  const participantLinks = (song.artist_names && song.artist_names.length ? song.artist_names : [song.artist_name]).map((name) => (
    `<button class="artist-link" type="button" data-artist="${escapeHtml(name)}">${escapeHtml(name)}</button>`
  )).join("、");
  $("#songDetail").innerHTML = `
    <div class="breadcrumb">首页大盘 / 歌曲热度榜 / 歌曲详情</div>
    <article class="detail-hero">
      ${coverHtml(song.cover_url, song.song_name)}
      <div class="detail-copy">
        <div class="tag-row"><span class="tag">歌曲</span>${labels.map((label) => `<span class="tag">${escapeHtml(label)}</span>`).join("")}</div>
        <h2>《${escapeHtml(song.song_name)}》</h2>
        <p class="muted">歌手：${participantLinks}</p>
        <div class="meta-grid">
          <span>风格：${escapeHtml(style.name)}</span>
          ${song.album_name ? `<span>专辑：${escapeHtml(song.album_name)}</span>` : ""}
          <span>当前排名：${score.rank ? `第 ${formatNumber(score.rank)} 名` : "--"}</span>
          ${score.rank_delta ? `<span>较昨日：${score.rank_delta > 0 ? "上升" : "下降"} ${Math.abs(score.rank_delta)} 名</span>` : ""}
        </div>
      </div>
      <div class="score-panel">
        <small>综合热度分</small>
        <strong>${formatNumber(score.heat_score)}</strong>
        <span>${platformCoverage.coverageText || "--"} 覆盖 · ${platformConfidence || "--"}可信度</span>
        <button class="ghost-button" type="button">加入监测</button>
      </div>
    </article>

    <section class="detail-grid">
      <article class="panel" id="songScoreBreakdown">
        <div class="panel-head"><h2>热度分数构成</h2><span>现有公式解释</span></div>
        <div id="songScoreBreakdownBody"><p class="muted">正在加载分数构成...</p></div>
      </article>
      <article class="panel" id="songPlatformPerformance">
        <div class="panel-head"><h2>该歌曲在各平台的表现</h2><span>本次主榜采集</span></div>
        <div id="songPlatformPerformanceBody">${platformPerformanceError ? `<p class="muted">暂时无法加载平台表现。</p>` : songPlatformPerformanceHtml(platformPerformance)}</div>
      </article>
    </section>

    <section class="three-column">
      <article class="panel">
        <div class="panel-head">
          <h2>近 30 天热度趋势</h2>
          <div class="segmented"><button class="active" type="button">30天</button></div>
        </div>
        ${trendStatsHtml(trendStats)}
        ${lineChart(recentTrend)}
      </article>
      <article class="panel">
        <div class="panel-head"><h2>跨平台热度来源</h2><span>${platformCoverage.coverageText || "--"}</span></div>
        ${renderSongPlatformHeatSource(platformPerformance)}
      </article>
      <article class="panel ai-card" id="songAiAnalysis">
        <div class="panel-head"><h2>AI 热度变化分析</h2><span>AI生成</span></div>
        <div id="songAiAnalysisBody">${renderAIHeatAnalysisBlock({ status: "loading" })}</div>
      </article>
    </section>

    <section class="soft-note">数据来源：三大音乐平台公开榜单及真实采集到的用户评论数据，AI 模型综合计算得出。</section>
  `;
  const songAiPayload = {
    song_id: Number(songId),
    song_name: song.song_name,
    artist_name: song.artist_name,
    heat_trend: recentTrend,
    platform_performance: platformPerformanceItems(platformPerformance),
    representative_metrics: score,
    enable_web_search: true,
  };
  state.ai.song = { songId, payload: songAiPayload };
  loadSongScoreBreakdown(songId);
  loadSongAnalysis(songId, songAiPayload);
}

function buildArtistStyleRows(songs) {
  const buckets = new Map();
  songs.forEach((song) => {
    const style = tagForSong(song);
    buckets.set(style.name, (buckets.get(style.name) || 0) + Number(song.heat_score || 0));
  });
  return [...buckets.entries()].sort((a, b) => b[1] - a[1]).map(([name, score]) => ({ name, score }));
}

function artistStyleChart(rows) {
  const max = Math.max(...rows.map((row) => row.score), 1);
  return `
    <div class="style-bars">
      ${rows.map((row) => `
        <div class="style-bar">
          <span>${escapeHtml(row.name)}</span>
          <i style="width:${Math.max(8, (row.score / max) * 100)}%"></i>
        </div>
      `).join("") || `<p class="muted">暂无风格数据</p>`}
    </div>
  `;
}

function artistTrendFromSongs(songs) {
  const base = songs.reduce((sum, song) => sum + Number(song.heat_score || 0), 0) || 0;
  return Array.from({ length: 30 }, (_, index) => ({
    score_date: index + 1,
    heat_score: base ? base * (0.86 + (index % 7) * 0.018 + index * 0.004) : 0,
  }));
}

function firstPresentValue(item, keys) {
  for (const key of keys) {
    if (item?.[key] !== undefined && item?.[key] !== null && item?.[key] !== "") return item[key];
  }
  return null;
}

function renderRepresentativeSongItem(song, index, options = {}) {
  const songName = firstPresentValue(song, ["song_name", "title", "name"]) || "--";
  const songId = firstPresentValue(song, ["song_id", "id"]);
  const artistName = firstPresentValue(song, ["artist_name", "primary_artist_name", "artist"]);
  const coverUrl = firstPresentValue(song, ["cover_url", "album_cover", "image_url"]);
  const heat = firstPresentValue(song, ["heat_score", "avg_heat", "avg_heat_score", "score", "adjusted_heat", "total_score"]);
  const rowAttrs = songId ? ` data-song-id="${escapeHtml(songId)}"` : "";
  const heatMeta = heat !== null ? `<span>热度：${formatNumber(heat)}</span>` : "";
  const artistMeta = options.showArtist && artistName
    ? `<button class="inline-artist-link" type="button" data-artist="${escapeHtml(artistName)}">${escapeHtml(artistName)}</button>`
    : "";

  return `
    <div class="representative-song-row"${rowAttrs} role="${songId ? "button" : "group"}" tabindex="${songId ? "0" : "-1"}">
      <span class="representative-song-rank">${index + 1}</span>
      ${thumbHtml(coverUrl, songName)}
      <span class="representative-song-copy">
        <b>${escapeHtml(songName)}</b>
        <small>${[artistMeta, heatMeta].filter(Boolean).join("<i>|</i>")}</small>
      </span>
      <span class="representative-song-arrow">›</span>
    </div>
  `;
}

function renderRepresentativeSongsList(songs, options = {}) {
  const visibleSongs = (songs || []).filter(Boolean);
  if (!visibleSongs.length) return emptyText("暂无歌曲数据");
  return `
    <div class="representative-song-list">
      ${visibleSongs.map((song, index) => renderRepresentativeSongItem(song, index, options)).join("")}
    </div>
  `;
}

function representativeSongScore(song) {
  return Number(
    song?.heat_score
    || song?.avg_heat
    || song?.avg_heat_score
    || song?.score
    || song?.adjusted_heat
    || song?.total_score
    || 0
  );
}

function compareRepresentativeSongs(a, b) {
  const heatDiff = representativeSongScore(b) - representativeSongScore(a);
  if (heatDiff) return heatDiff;
  const platformDiff = Number(b?.platform_count || 0) - Number(a?.platform_count || 0);
  if (platformDiff) return platformDiff;
  const rankDiff = Number(a?.best_rank || a?.rank || 999999) - Number(b?.best_rank || b?.rank || 999999);
  if (rankDiff) return rankDiff;
  return 0;
}

function selectRepresentativeSongs(artist) {
  const explicit = Array.isArray(artist?.representative_songs) ? artist.representative_songs : null;
  if (explicit && explicit.length) return explicit.filter(Boolean).slice(0, 3);
  const candidateSongs = artist?.top_songs || artist?.charted_songs || artist?.related_songs || artist?.songs || [];
  return candidateSongs.filter(Boolean).slice().sort(compareRepresentativeSongs).slice(0, 3);
}

function renderAiAnalysis(data) {
  const content = String(data.analysis || data.content || "").trim();
  if (!content) {
    return renderAIHeatAnalysisBlock({
      status: "error",
      error_message: "AI 未返回有效分析内容，请稍后重试。",
    });
  }
  return renderAIHeatAnalysisBlock({ status: "success", analysis: content });
}

function renderAIHeatAnalysisBlock(aiState = {}, retryType = "") {
  const status = aiState.status || "loading";
  if (status === "loading") {
    return `<p class="muted ai-status-text">AI 正在分析近期热度变化...</p>`;
  }
  if (status === "success") {
    return `<div class="analysis-content">${escapeHtml(aiState.analysis || "").replace(/\n/g, "<br />")}</div>`;
  }

  const message = status === "not_configured"
    ? "AI 服务未配置，无法生成热度变化分析。"
    : (aiState.error_message || "AI 分析生成失败，请检查 AI 服务配置或稍后重试。");
  return `
    <div class="ai-error-state">
      <p>${escapeHtml(message)}</p>
      ${retryType ? `<button class="ghost-button" type="button" data-ai-retry="${escapeHtml(retryType)}">重新生成</button>` : ""}
    </div>
  `;
}

function aiErrorState(error) {
  const message = String(error?.message || "");
  if (message.includes("未配置") || message.toLowerCase().includes("not configured")) {
    return { status: "not_configured", error_message: "AI 服务未配置，无法生成热度变化分析。" };
  }
  if (message.includes("未返回有效分析内容")) {
    return { status: "error", error_message: "AI 未返回有效分析内容，请稍后重试。" };
  }
  return { status: "error", error_message: "AI 分析生成失败，请检查 AI 服务配置或稍后重试。" };
}

async function fetchAIHeatAnalysis(path, payload) {
  const data = await api(path, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const analysis = String(data.analysis || data.content || "").trim();
  if (!analysis) throw new Error("AI 未返回有效分析内容，请稍后重试。");
  return { ...data, analysis };
}

async function loadAIAnalysisPanel({ target, path, payload, retryType, logMessage }) {
  const node = $(target);
  if (node) node.innerHTML = renderAIHeatAnalysisBlock({ status: "loading" });
  try {
    const data = await fetchAIHeatAnalysis(path, payload);
    $(target).innerHTML = renderAiAnalysis(data);
  } catch (error) {
    console.warn(logMessage, error);
    if (node) node.innerHTML = renderAIHeatAnalysisBlock(aiErrorState(error), retryType);
  }
}

async function settledRequestMap(requestEntries, warningPrefix) {
  const settled = await Promise.allSettled(requestEntries.map(([, request]) => request));
  const data = {};
  const failed = [];

  settled.forEach((result, index) => {
    const key = requestEntries[index][0];
    if (result.status === "fulfilled") {
      data[key] = result.value;
    } else {
      failed.push(key);
      console.warn(`${warningPrefix}：${key}`, result.reason);
    }
  });

  return { data, failed };
}

function aiInsightList(items) {
  return `<ul class="insight-list">${items.filter(Boolean).slice(0, 4).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

async function loadSongAnalysis(songId, payload = null) {
  await loadAIAnalysisPanel({
    target: "#songAiAnalysisBody",
    path: "/api/ai/analyze-song-heat",
    payload: payload || state.ai.song?.payload || { song_id: Number(songId), enable_web_search: true },
    retryType: "song",
    logMessage: "Song AI analysis request failed",
  });
}

async function loadSongPlatformPerformance(songId) {
  try {
    const data = await api(`/api/songs/${songId}/platform-performance?chart_type=hot`);
    $("#songPlatformPerformanceBody").innerHTML = songPlatformPerformanceHtml(data);
  } catch (error) {
    console.warn("Song platform performance request failed", error);
    $("#songPlatformPerformanceBody").innerHTML = `<p class="muted">暂时无法加载平台表现。</p>`;
  }
}

async function loadSongScoreBreakdown(songId) {
  try {
    const data = await api(`/api/analytics/song-score-breakdown/${songId}`);
    $("#songScoreBreakdownBody").innerHTML = scoreBreakdownHtml(data);
  } catch (error) {
    console.warn("Song score breakdown request failed", error);
    $("#songScoreBreakdownBody").innerHTML = `<p class="muted">暂时无法加载分数构成。</p>`;
  }
}

async function loadArtistAnalysis(artistName, payload = null) {
  await loadAIAnalysisPanel({
    target: "#artistAiAnalysisBody",
    path: "/api/ai/analyze-artist-heat",
    payload: payload || state.ai.artist?.payload || { artist_name: artistName, enable_web_search: true },
    retryType: "artist",
    logMessage: "Artist AI analysis request failed",
  });
}

async function loadArtistPlatformPerformance(artistName) {
  try {
    const data = await api(`/api/artists/${encodeURIComponent(artistName)}/platform-performance?chart_type=hot`);
    $("#artistPlatformPerformanceBody").innerHTML = artistPlatformPerformanceHtml(data);
  } catch (error) {
    console.warn("Artist platform performance request failed", error);
    $("#artistPlatformPerformanceBody").innerHTML = `<p class="muted">暂时无法加载平台表现。</p>`;
  }
}

function aggregateStyleDistribution(items) {
  const buckets = new Map();
  items.forEach((item, index) => {
    const rawName = item.primary_style || item.normalized_style || item.style_name || item.name || item.style;
    const styleName = normalizeStyleName(rawName);
    if (!styleName || !PRIMARY_STYLE_NAMES.has(styleName)) return;
    const def = styleDefForName(styleName, index);
    const songs = Array.isArray(item.songs) ? item.songs : [];
    const songCount = Number(item.song_count || item.songCount || songs.length || 0);
    const bucket = buckets.get(styleName) || {
      name: styleName,
      key: styleName,
      color: item.color || def.color,
      songs: [],
      platforms: new Set(),
      songCount: 0,
      desc: item.desc || def.desc || "基于平台原生风格榜单统计",
      tags: item.tags || def.tags || [styleName, "平台原生榜单"],
    };
    bucket.songs.push(...songs);
    bucket.songCount += songCount;
    (item.platforms || []).forEach((platform) => bucket.platforms.add(platform));
    if (!bucket.color && item.color) bucket.color = item.color;
    buckets.set(styleName, bucket);
  });

  return [...buckets.values()].map((bucket, index) => {
    const seenSongs = new Set();
    const songs = bucket.songs.filter((song) => {
      const key = song.song_id || `${song.song_name || ""}|${song.artist_name || ""}`;
      if (seenSongs.has(key)) return false;
      seenSongs.add(key);
      return true;
    });
    const def = styleDefForName(bucket.name, index);
    return {
      ...bucket,
      color: bucket.color || def.color,
      songs,
      platforms: [...bucket.platforms],
      songCount: bucket.songCount || songs.length,
    };
  }).sort((a, b) => styleWeight(b) - styleWeight(a));
}

function deriveStyleBucketsFromSongs(songs) {
  const buckets = new Map();
  (songs || []).forEach((song) => {
    const style = tagForSong(song);
    if (!style || !PRIMARY_STYLE_NAMES.has(style.name)) return;
    const bucket = buckets.get(style.name) || {
      name: style.name,
      key: style.name,
      color: style.color,
      songs: [],
      platforms: new Set(),
      songCount: 0,
      desc: style.desc,
      tags: style.tags,
    };
    bucket.songs.push(song);
    bucket.songCount += 1;
    sourcePlatforms(song).forEach((platform) => bucket.platforms.add(platform));
    buckets.set(style.name, bucket);
  });
  return [...buckets.values()].map((bucket) => ({ ...bucket, platforms: [...bucket.platforms] }));
}

function normalizeStyleBuckets(styleBuckets) {
  const items = Array.isArray(styleBuckets?.items) ? styleBuckets.items : [];
  const apiBuckets = aggregateStyleDistribution(items);
  return ensureCoreStylesVisible(apiBuckets, 50);
}

async function openArtist(artistName) {
  if (!artistName) return;
  switchView("artist");
  $("#artistDetail").innerHTML = `<article class="panel">加载歌手详情中...</article>`;
  const data = await api(`/api/artists/${encodeURIComponent(artistName)}`);
  const songs = data.songs || [];
  const representativeSongs = selectRepresentativeSongs({ ...data, songs });
  const topSong = songs[0] || {};
  const artistRank = state.artists.find((item) => item.artist_name === artistName);
  const sum = songs.reduce((acc, song) => {
    acc.netease_score += Number(song.netease_score || 0);
    acc.qq_score += Number(song.qq_score || 0);
    acc.kugou_score += Number(song.kugou_score || 0);
    return acc;
  }, { netease_score: 0, qq_score: 0, kugou_score: 0 });
  const values = platformValues(sum);
  const styleRows = buildArtistStyleRows(songs);
  const mainStyleName = styleRows[0]?.name || tagForSong(topSong).name;
  const totalScore = artistRank?.artist_heat_score || artistRank?.total_score || songs.reduce((sumValue, song) => sumValue + Number(song.heat_score || 0), 0);
  const artistTrend = (data.trend && data.trend.length ? data.trend : artistTrendFromSongs(songs)).slice(-30);
  $("#artistDetail").innerHTML = `
    <div class="breadcrumb">首页大盘 / 热门歌手总榜 / 歌手详情</div>
    <article class="detail-hero">
      ${coverHtml(data.artist_avatar_url || topSong.artist_avatar_url, artistName, "artist-avatar")}
      <div class="detail-copy">
        <div class="tag-row"><span class="tag">歌手</span><span class="tag">${escapeHtml(mainStyleName)}</span></div>
        <h2>${escapeHtml(artistName)}</h2>
        <p class="muted">基于三平台公开歌手榜或歌手推荐列表数据生成综合表现。</p>
        <div class="meta-grid">
          <span>当前排名：${artistRank?.rank ? `第 ${formatNumber(artistRank.rank)} 名` : "--"}</span>
          <span>代表歌曲：${escapeHtml(topSong.song_name || "--")}</span>
          <span>上榜歌曲：${formatNumber(songs.length)} 首</span>
        </div>
      </div>
      <div class="score-panel">
        <small>综合热度得分</small>
        <strong>${formatNumber(totalScore)}</strong>
        <span>${artistRank?.platform_count ? `${artistRank.platform_count}/3 覆盖` : "覆盖待计算"}</span>
      </div>
    </article>

    <section class="detail-grid">
      <article class="panel">
        <div class="panel-head"><h2>代表歌曲</h2><span>点击进入歌曲详情</span></div>
        ${renderRepresentativeSongsList(representativeSongs)}
      </article>
      <article class="panel">
        <div class="panel-head"><h2>平台热度分布 / 覆盖情况</h2></div>
        <div class="chart-box artist-platform-distribution">${pieHtml(values)}</div>
        <div class="tag-row">${values.map((item) => `<span class="tag">${escapeHtml(item.name)} ${item.percent}%</span>`).join("")}</div>
      </article>
    </section>

    <article class="panel" id="artistPlatformPerformance">
      <div class="panel-head"><h2>该歌手在各平台的表现</h2><span>本次主榜采集</span></div>
      <div id="artistPlatformPerformanceBody"><p class="muted">正在加载平台表现...</p></div>
    </article>

    <section class="two-column">
      <article class="panel">
        <div class="panel-head"><h2>歌手近 30 天热度趋势</h2></div>
        ${lineChart(artistTrend)}
        <p class="muted">趋势解读：当前由${escapeHtml(topSong.song_name || "上榜歌曲")}带动，整体接近${escapeHtml(mainStyleName)}主导型。</p>
      </article>
      <article class="panel ai-card">
        <div class="panel-head"><h2>AI 热度变化分析</h2><span>AI生成</span></div>
        <div id="artistAiAnalysisBody">${renderAIHeatAnalysisBlock({ status: "loading" })}</div>
      </article>
    </section>
  `;
  const artistAiPayload = {
    artist_name: artistName,
    representative_songs: representativeSongs,
    platform_performance: values,
    heat_trend: artistTrend,
    enable_web_search: true,
  };
  state.ai.artist = { artistName, payload: artistAiPayload };
  loadArtistPlatformPerformance(artistName);
  loadArtistAnalysis(artistName, artistAiPayload);
}

async function loadDashboard() {
  const requestEntries = [
    ["dashboard", api("/api/charts/dashboard")],
    ["daily", api("/api/charts/daily-hot?limit=50")],
    ["weekly", api("/api/charts/weekly-hot?limit=50")],
    ["artists", api("/api/artists/rank?limit=50")],
    ["rising", api("/api/charts/rising?limit=50")],
    ["newSongs", api("/api/charts/new-songs?limit=50")],
    ["interactionHeat", api("/api/charts/interaction-heat?limit=50")],
    ["styleBuckets", api("/api/charts/style-buckets?limit=50")],
  ];
  const { data, failed } = await settledRequestMap(requestEntries, "接口加载失败");

  if (!Object.keys(data).length) {
    throw new Error("全部首页接口加载失败");
  }

  state.dashboard = data.dashboard || null;
  state.daily = data.daily?.items || data.dashboard?.daily_hot_top10 || [];
  state.weekly = data.weekly?.items || [];
  state.weeklyMessage = data.weekly?.message || "";
  state.artists = data.artists?.items || [];
  state.rising = data.rising?.items || [];
  state.newSongs = data.newSongs?.items || [];
  state.interactionHeat = data.interactionHeat?.items || [];
  state.styleMeta = data.styleBuckets ? {
    totalCanonicalSongs: data.styleBuckets.total_canonical_songs || 0,
    classifiedSongCount: data.styleBuckets.classified_song_count || data.styleBuckets.total_count || 0,
    unclassifiedSongCount: data.styleBuckets.unclassified_song_count || 0,
  } : null;
  state.styleBuckets = normalizeStyleBuckets(data.styleBuckets);
  setUpdateTime(state.dashboard?.score_date || state.dashboard?.chart_date || "--");
  renderDashboard();
  renderStyleCenter();

  if (failed.length) {
    toast(`部分接口加载失败：${failed.join("、")}`);
  }
}

async function loadCrossPlatformAnalysis(force = false) {
  if (state.crossPlatform && !force) {
    renderCrossPlatformAnalysis();
    return;
  }
  $("#crossPlatformContent").innerHTML = `<article class="panel">加载跨平台分析中...</article>`;
  const requestEntries = [
    ["counts", api("/api/analytics/platform-song-counts?chart_type=hot")],
    ["overlap", api("/api/analytics/topn-overlap?chart_type=hot")],
    ["similarity", api("/api/analytics/platform-similarity?chart_type=hot")],
    ["coverage", api("/api/analytics/coverage-distribution?chart_type=hot")],
    ["common", api("/api/analytics/common-songs-summary?chart_type=hot")],
  ];
  const { data, failed } = await settledRequestMap(requestEntries, "跨平台分析接口加载失败");
  state.crossPlatform = data;
  renderCrossPlatformAnalysis();
  if (failed.length) toast(`部分跨平台分析加载失败：${failed.join("、")}`);
}

function retryAIAnalysis(type) {
  if (type === "explore") {
    retryExploreAI();
    return;
  }
  if (type === "song" && state.ai.song) {
    loadSongAnalysis(state.ai.song.songId, state.ai.song.payload);
    return;
  }
  if (type === "artist" && state.ai.artist) {
    loadArtistAnalysis(state.ai.artist.artistName, state.ai.artist.payload);
  }
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const nav = event.target.closest(".nav-item");
    if (nav?.dataset.view) {
      switchView(nav.dataset.view);
      if (nav.dataset.view === "crossPlatform") {
        loadCrossPlatformAnalysis().catch((error) => toast(error.message));
      }
      if (nav.dataset.view === "explore" && !state.explorer.result) {
        renderSongExplorer();
      }
    }
    const viewButton = event.target.closest("[data-view]");
    if (!nav && viewButton?.dataset.view) {
      switchView(viewButton.dataset.view);
      if (viewButton.dataset.view === "crossPlatform") {
        loadCrossPlatformAnalysis().catch((error) => toast(error.message));
      }
      if (viewButton.dataset.view === "explore" && !state.explorer.result) {
        renderSongExplorer();
      }
    }

    const more = event.target.closest("[data-more]");
    if (more?.dataset.more) {
      openList(more.dataset.more);
    }

    const expand = event.target.closest("[data-expand]");
    if (expand?.dataset.expand) {
      const key = expand.dataset.expand;
      state.expanded[key] = !state.expanded[key];
      if (key === "style" && state.activeStyle) {
        showStyleDetail(state.activeStyle);
      } else {
        renderDashboard();
      }
    }

    const retry = event.target.closest("[data-ai-retry]");
    if (retry?.dataset.aiRetry) {
      retryAIAnalysis(retry.dataset.aiRetry);
      return;
    }

    const exploreExample = event.target.closest("[data-explore-keyword]");
    if (exploreExample?.dataset.exploreKeyword) {
      $("#exploreKeyword").value = exploreExample.dataset.exploreKeyword;
      searchExploreSong(exploreExample.dataset.exploreKeyword).catch((error) => toast(error.message));
      return;
    }

    const artist = event.target.closest("[data-artist]");
    if (artist?.dataset.artist) {
      openArtist(artist.dataset.artist).catch((error) => toast(error.message));
      return;
    }

    const song = event.target.closest("[data-song-id]");
    if (song?.dataset.songId) {
      openSong(song.dataset.songId).catch((error) => toast(error.message));
    }

    const style = event.target.closest("[data-style]");
    if (style?.dataset.style) {
      switchView("styles");
      showStyleDetail(style.dataset.style);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    const row = event.target.closest(".representative-song-row[data-song-id]");
    if (!row?.dataset.songId) return;
    event.preventDefault();
    openSong(row.dataset.songId).catch((error) => toast(error.message));
  });

  $("#backToStyles").addEventListener("click", () => {
    $("#styleCards").classList.remove("hidden");
    $("#styleDetail").classList.add("hidden");
    $("#backToStyles").classList.add("hidden");
    state.activeStyle = "";
    state.expanded.style = false;
  });

  $("#exploreSearchForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const keyword = $("#exploreKeyword").value.trim();
    if (keyword) searchExploreSong(keyword).catch((error) => toast(error.message));
  });

  $("#aiSongSearchForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const query = $("#aiSongQuery").value.trim();
    if (query) searchAiSongs(query).catch((error) => toast(error.message));
  });

  window.addEventListener("beforeunload", () => cleanupExploreSession(true));
}

async function bootstrap() {
  bindEvents();
  try {
    await checkBackend();
  } catch (error) {
    setApiStatus("后端未连接");
    $("#dailyHotList").innerHTML = emptyText(`接口连接失败，请确认后端运行在 ${API_BASE}。`);
    toast(`接口连接失败：${error.message}`);
    return;
  }

  try {
    await loadDashboard();
  } catch (error) {
    $("#dailyHotList").innerHTML = emptyText(`首页数据加载失败：${error.message}`);
    toast(`首页数据加载失败：${error.message}`);
  }
}


bootstrap();

