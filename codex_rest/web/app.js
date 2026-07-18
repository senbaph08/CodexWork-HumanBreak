(() => {
  "use strict";

  // The token stays in the URL fragment: fragments are never sent in HTTP
  // requests or referrer headers, and keeping it makes a manual reload safe.
  const token = location.hash.slice(1);
  const isSettings = location.pathname === "/settings";
  const restView = document.getElementById("restView");
  const settingsView = document.getElementById("settingsView");
  restView.hidden = isSettings;
  settingsView.hidden = !isSettings;

  let currentState = null;
  let audioContext = null;
  let master = null;
  let musicBus = null;
  let scheduler = null;
  let chordIndex = 0;
  let customAudio = null;
  let customSource = null;
  let playlistIndex = 0;
  let controlsTimer = null;
  let finishing = false;

  const api = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    headers.set("X-Codex-Rest-Token", token);
    if (options.body && typeof options.body === "string") headers.set("Content-Type", "application/json");
    const response = await fetch(path, {...options, headers});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Request failed");
    return data;
  };

  const saveSettings = async changes => {
    const updated = await api("/api/settings", {method: "POST", body: JSON.stringify(changes)});
    if (currentState) currentState.settings = updated;
    return updated;
  };

  const ensureAudio = () => {
    if (audioContext) return audioContext;
    audioContext = new AudioContext();
    master = audioContext.createGain();
    musicBus = audioContext.createGain();
    const compressor = audioContext.createDynamicsCompressor();
    compressor.threshold.value = -24;
    compressor.knee.value = 20;
    compressor.ratio.value = 4;
    musicBus.connect(compressor).connect(master).connect(audioContext.destination);
    return audioContext;
  };

  const fadeMusic = (enabled, seconds = .45) => {
    if (!musicBus || !currentState) return;
    const now = audioContext.currentTime;
    const target = enabled ? currentState.settings.music_volume : 0.0001;
    musicBus.gain.cancelScheduledValues(now);
    musicBus.gain.setValueAtTime(Math.max(.0001, musicBus.gain.value), now);
    musicBus.gain.exponentialRampToValueAtTime(Math.max(.0001, target), now + seconds);
  };

  const softTone = (frequency, start, duration, amount, type = "sine") => {
    const osc = audioContext.createOscillator();
    const gain = audioContext.createGain();
    const filter = audioContext.createBiquadFilter();
    osc.type = type;
    osc.frequency.value = frequency;
    filter.type = "lowpass";
    filter.frequency.value = 1500;
    gain.gain.setValueAtTime(.0001, start);
    gain.gain.exponentialRampToValueAtTime(amount, start + .6);
    gain.gain.exponentialRampToValueAtTime(.0001, start + duration);
    osc.connect(filter).connect(gain).connect(musicBus);
    osc.start(start);
    osc.stop(start + duration + .05);
  };

  const scheduleChord = () => {
    if (!audioContext || !currentState?.settings.music_enabled || currentState.settings.music_source !== "builtin") return;
    const progression = [
      [196.00, 246.94, 293.66, 369.99],
      [174.61, 220.00, 261.63, 329.63],
      [146.83, 196.00, 246.94, 293.66],
      [164.81, 207.65, 246.94, 311.13],
    ];
    const now = audioContext.currentTime + .08;
    const chord = progression[chordIndex++ % progression.length];
    chord.forEach((note, index) => softTone(note, now + index * .07, 7.7, .022, index % 2 ? "sine" : "triangle"));
    softTone(chord[2] * 2, now + 1.15, 2.1, .014, "sine");
    softTone(chord[1] * 2, now + 3.1, 2.5, .011, "sine");
  };

  const stopCustom = () => {
    if (customAudio) {
      customAudio.pause();
      customAudio.removeAttribute("src");
      customAudio.load();
    }
    customAudio = null;
    customSource = null;
  };

  const playCustom = () => {
    const tracks = currentState?.settings.tracks || [];
    if (!tracks.length) {
      saveSettings({music_source: "builtin"}).then(() => startMusic());
      return;
    }
    stopCustom();
    if (currentState.settings.playlist_order === "shuffle") playlistIndex = Math.floor(Math.random() * tracks.length);
    else playlistIndex %= tracks.length;
    const track = tracks[playlistIndex];
    customAudio = new Audio(`/media/${encodeURIComponent(track.id)}?t=${encodeURIComponent(token)}`);
    customAudio.preload = "auto";
    customSource = audioContext.createMediaElementSource(customAudio);
    customSource.connect(musicBus);
    customAudio.addEventListener("ended", () => { playlistIndex += 1; playCustom(); }, {once: true});
    customAudio.addEventListener("error", () => { playlistIndex += 1; if (playlistIndex < tracks.length * 2) playCustom(); else saveSettings({music_source: "builtin"}).then(startMusic); }, {once: true});
    customAudio.play().catch(() => {});
  };

  const startMusic = () => {
    if (!currentState?.settings.music_enabled || isSettings) return;
    ensureAudio().resume().catch(() => {});
    musicBus.gain.value = Math.max(.0001, currentState.settings.music_volume);
    clearInterval(scheduler);
    if (currentState.settings.music_source === "playlist" && currentState.settings.tracks.length) {
      playCustom();
    } else {
      stopCustom();
      scheduleChord();
      scheduler = setInterval(scheduleChord, 7600);
    }
  };

  const stopMusic = (seconds = .35) => {
    if (musicBus) fadeMusic(false, seconds);
    setTimeout(() => {
      clearInterval(scheduler);
      scheduler = null;
      stopCustom();
    }, seconds * 1000 + 60);
  };

  const setToggle = (element, label, value, icon) => {
    element.setAttribute("aria-pressed", String(value));
    element.setAttribute("aria-label", `${label} ${value ? "ON" : "OFF"}`);
    element.innerHTML = `<span aria-hidden="true">${icon}</span><span>${label}</span><strong>${value ? "ON" : "OFF"}</strong>`;
  };

  const syncRestControls = settings => {
    setToggle(document.getElementById("musicToggle"), "音楽", settings.music_enabled, "♫");
    setToggle(document.getElementById("chimeToggle"), "完了通知音", settings.completion_sound_enabled, "♢");
    document.getElementById("musicVolume").value = settings.music_volume;
    document.getElementById("chimeVolume").value = settings.completion_volume;
  };

  const finish = () => {
    if (finishing) return;
    finishing = true;
    stopMusic(1.45);
    document.body.classList.add("finishing");
  };

  const poll = async () => {
    try {
      const state = await api("/api/state");
      const previous = currentState;
      currentState = state;
      if (!isSettings) {
        syncRestControls(state.settings);
        if (!previous && state.settings.music_enabled) startMusic();
        if (state.phase === "finishing") finish();
        if (state.phase === "active" && finishing) location.reload();
      } else renderSettings(state.settings);
    } catch (_) {}
  };

  if (!isSettings) {
    document.getElementById("musicToggle").addEventListener("click", async () => {
      const enabled = !currentState.settings.music_enabled;
      await saveSettings({music_enabled: enabled});
      syncRestControls(currentState.settings);
      if (enabled) startMusic(); else stopMusic();
    });
    document.getElementById("chimeToggle").addEventListener("click", async () => {
      await saveSettings({completion_sound_enabled: !currentState.settings.completion_sound_enabled});
      syncRestControls(currentState.settings);
    });
    document.getElementById("musicVolume").addEventListener("input", event => {
      currentState.settings.music_volume = Number(event.target.value);
      if (musicBus && currentState.settings.music_enabled) musicBus.gain.value = Math.max(.0001, currentState.settings.music_volume);
    });
    document.getElementById("musicVolume").addEventListener("change", event => saveSettings({music_volume: Number(event.target.value)}));
    document.getElementById("chimeVolume").addEventListener("change", event => saveSettings({completion_volume: Number(event.target.value)}));
    document.getElementById("closeRest").addEventListener("click", () => api("/api/close", {method: "POST", body: "{}"}));
    document.addEventListener("mousemove", () => {
      document.body.classList.add("controls-visible");
      clearTimeout(controlsTimer);
      controlsTimer = setTimeout(() => document.body.classList.remove("controls-visible"), 2600);
    });
    setInterval(() => {
      if (!currentState?.started_at) return;
      const seconds = Math.max(0, Math.floor(Date.now() / 1000 - currentState.started_at));
      document.getElementById("elapsed").textContent = `${String(Math.floor(seconds / 60)).padStart(2,"0")}:${String(seconds % 60).padStart(2,"0")}`;
    }, 1000);
  }

  let settingsRendered = false;
  const renderSettings = settings => {
    if (settingsRendered) return;
    settingsRendered = true;
    const musicButton = document.getElementById("settingsMusicToggle");
    const chimeButton = document.getElementById("settingsChimeToggle");
    setToggle(musicButton, "音楽", settings.music_enabled, "♫");
    setToggle(chimeButton, "完了通知音", settings.completion_sound_enabled, "♢");
    document.getElementById("settingsMusicVolume").value = settings.music_volume;
    document.getElementById("settingsChimeVolume").value = settings.completion_volume;
    document.querySelector(`input[name="musicSource"][value="${settings.music_source}"]`).checked = true;
    document.getElementById("playlistOrder").value = settings.playlist_order;
    renderTrackList(settings.tracks);
  };

  const renderTrackList = tracks => {
    const list = document.getElementById("trackList");
    list.replaceChildren(...tracks.map(track => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = track.name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "削除";
      remove.addEventListener("click", async () => {
        await api(`/api/tracks/${encodeURIComponent(track.id)}`, {method: "DELETE"});
        settingsRendered = false;
        await poll();
      });
      item.append(name, remove);
      return item;
    }));
  };

  if (isSettings) {
    document.getElementById("settingsMusicToggle").addEventListener("click", async () => { await saveSettings({music_enabled: !currentState.settings.music_enabled}); settingsRendered = false; poll(); });
    document.getElementById("settingsChimeToggle").addEventListener("click", async () => { await saveSettings({completion_sound_enabled: !currentState.settings.completion_sound_enabled}); settingsRendered = false; poll(); });
    document.getElementById("settingsMusicVolume").addEventListener("change", event => saveSettings({music_volume: Number(event.target.value)}));
    document.getElementById("settingsChimeVolume").addEventListener("change", event => saveSettings({completion_volume: Number(event.target.value)}));
    document.querySelectorAll('input[name="musicSource"]').forEach(input => input.addEventListener("change", event => saveSettings({music_source: event.target.value})));
    document.getElementById("playlistOrder").addEventListener("change", event => saveSettings({playlist_order: event.target.value}));
    document.getElementById("trackUpload").addEventListener("change", async event => {
      const status = document.getElementById("uploadStatus");
      for (const file of event.target.files) {
        status.textContent = `${file.name} を取り込んでいます…`;
        try {
          await api("/api/tracks", {method: "POST", headers: {"X-File-Name": encodeURIComponent(file.name)}, body: file});
        } catch (error) { status.textContent = `${file.name}: ${error.message}`; }
      }
      status.textContent = "取り込みが完了しました。";
      event.target.value = "";
      settingsRendered = false;
      await poll();
    });
  }

  poll();
  setInterval(poll, 500);
})();
