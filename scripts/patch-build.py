"""Patch the upstream marketplace build for Spotify 1.3.x.

Usage: python3 scripts/patch-build.py <upstream cat-jam.js> <output cat-jam.js>

- Find the player bar / library container without Spotify's old mapped class names.
- Fall back to Deezer BPM (via ISRC) when Spotify's audio analysis is unavailable.
- Halve double-time tempos for slow songs ("Half-time for slow songs" setting).
- Stop the dead audio-features endpoint from turning the BPM into NaN.
"""
import sys

src = open(sys.argv[1]).read()


def sub(old, new):
    global src
    assert src.count(old) == 1, old
    src = src.replace(old, new)


# Spotify 1.3.x dropped the mapped class names; target the bar's right column structurally.
sub('("Bottom (Player)"===i?".main-nowPlayingBar-right":".main-yourLibraryX-libraryItemContainer")',
    '("Bottom (Player)"===i?\'.main-nowPlayingBar-right, [data-testid="now-playing-bar"] div:has(> [data-testid="player-controls"]) + div\':".main-yourLibraryX-libraryItemContainer, #Desktop_LeftSidebar_Id")')

# Left sidebar container must be positioned for the absolute-positioned video.
sub('o.firstChild?o.insertBefore(s,o.firstChild):o.appendChild(s)',
    '"Bottom (Player)"!==i&&"static"===getComputedStyle(o).position&&(o.style.position="relative"),o.firstChild?o.insertBefore(s,o.firstChild):o.appendChild(s)')

# Spotify's audio-analysis endpoint is gone: fall back to Deezer BPM via ISRC.
sub('try{return await Spicetify.getAudioData()}', 'try{return await catjamAudioData()}')

# audio-features is dead: after the first failure, skip it instead of waiting on every song.
sub('await Spicetify.CosmosAsync.get("https://api.spotify.com/v1/audio-features/"+n)',
    'await (catjamNoFeatures?Promise.reject(new Error("audio-features unavailable")):catjamTimeout(Spicetify.CosmosAsync.get("https://api.spotify.com/v1/audio-features/"+n),3e3).then(r=>{if("number"!=typeof r?.danceability)throw new Error("audio-features unavailable");return r}).catch(e=>{catjamNoFeatures=!0;throw e}))')

# Never let a bad "better BPM" (NaN) silently reset the cat to 1x.
sub('e=await b(a),', 'e=await b(a),Number.isFinite(e)&&e>0||(e=a),')

# Fold double-time tempos before computing the playback rate.
sub('async function y(a){let i=', 'async function y(a){a=catjamFold(a);let i=')

# Setting to control the half-time fold.
sub('f.addInput("catjam-webm-position-left-size"',
    'f.addDropDown("catjam-halftime","Half-time for slow songs (analysis often reports slow songs at double tempo)",["Auto (quiet songs)","Off","Always"],0),f.addInput("catjam-webm-position-left-size"')

# songchange stored fresh audio data in a local only; keep the shared copy used for resync current.
sub('a?(i=await g(),', 'a?(i=l=await g(),')

helpers = r'''
const catjamTimeout=(p,ms=4e3)=>{let t;return Promise.race([p,new Promise((_,r)=>{t=setTimeout(()=>r(new Error("timeout")),ms)})]).finally(()=>clearTimeout(t))};
const catjamCacheKey="catjam-bpm-cache",catjamMisses=new Set;let catjamNoFeatures=!1;
// Beat trackers often report slow songs at double their felt tempo. Auto halves fast tempos
// the analysis is unsure of, or that come from quiet, sparse songs (piano, lo-fi); confident
// fast tempos (e.g. Blinding Lights, 171 BPM) are left alone.
function catjamFold(a){
  const t=a?.track;if(!t?.tempo)return a;
  let mode;try{mode=JSON.parse(localStorage.getItem("catjam-settings.catjam-halftime")||"{}").value}catch(e){}
  mode=mode||"Auto (quiet songs)";
  const auto=t.tempo>=110&&(t.loudness<-12||t.tempo_confidence<.3);
  const half=mode==="Always"||mode!=="Off"&&auto;
  if(!half)return a;
  console.log("[CAT-JAM] Half-time:",t.tempo,"->",t.tempo/2);
  return{...a,track:{...t,tempo:t.tempo/2}};
}
function catjamCache(id,v){try{const c=JSON.parse(localStorage.getItem(catjamCacheKey)||"{}");if(v===void 0)return c[id];c[id]=v;const k=Object.keys(c);k.length>300&&delete c[k[0]];localStorage.setItem(catjamCacheKey,JSON.stringify(c))}catch(e){}}
async function catjamAudioData(){
  for(let n=0;n<50&&!Spicetify.Player.data?.item?.uri;n++)await new Promise(r=>setTimeout(r,100));
  try{const d=await catjamTimeout(Spicetify.getAudioData());if(d?.track?.tempo)return d}catch(e){}
  const item=Spicetify.Player.data?.item,id=item?.uri?.split(":").pop();
  if(!id||catjamMisses.has(id))return null;
  let bpm=catjamCache(id);
  if(bpm===void 0){
    try{
      let isrc=item.metadata?.isrc;
      if(!isrc){const t=await catjamTimeout(Spicetify.CosmosAsync.get("https://api.spotify.com/v1/tracks/"+id));isrc=t?.external_ids?.isrc}
      if(!isrc)throw new Error("no ISRC");
      const dz=await catjamTimeout(Spicetify.CosmosAsync.get("https://api.deezer.com/track/isrc:"+encodeURIComponent(isrc)));
      if(!(dz?.bpm>0))throw new Error("no Deezer BPM");
      bpm={tempo:dz.bpm,loudness:dz.gain};
      catjamCache(id,bpm);
    }catch(e){console.warn("[CAT-JAM] No BPM for this track:",e?.message||e);catjamMisses.add(id);return null}
  }
  console.log("[CAT-JAM] Deezer BPM:",bpm.tempo);
  return{track:bpm};
}
'''
# Insert helpers inside the IIFE, right after it waits for React.
anchor = 'await new Promise(e=>setTimeout(e,10));'
sub(anchor, anchor + helpers)

open(sys.argv[2], "w").write(src)
