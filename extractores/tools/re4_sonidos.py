#!/usr/bin/env python3
"""RE4 (GameCube, G4BE08) sound-effect extractor.

Reads the SE banks straight from the retail .rvz (via decomp-toolkit `dtk vfs cp`, cached under
re3_w3d/extracted/) and decodes them to 16-bit PCM WAV.

Format (from the decomp: src/game/dvd.cpp readMain, src/game/snd.cpp SndBlkInit,
src/game/snd_sub3.cpp Snd_iss_blk_init, src/game/snd_iss3.cpp iss_ax_set_wt_ptr/iss_ax_set_para,
include/dvd.h DvdHeader, include/snd_drv.h SND_SIT, include/dolphin/syn.h WT*):

* .das/.drs files start with a DvdHeader table at 0x20 (0x20-byte entries: type,size,dest,ofs,
  sndType,sndArg,sndNo). type 4 = nested table at ofs; inside it type 1 (TRANS_SND_BLK) is the
  bank's MRAM part and type 2 (TRANS_SND_PCM) the ARAM part (raw DSP-ADPCM frames).
  sndType = sound block: 0 CORE (etc/core.das), 1 PL (em/pl00.drs), 2 WEP (em/wepNN.drs),
  5 FOOT and 6 ROOM (St*/rNNN.das), 7 DOOR (bgm/doorse.dat), 8 ENEMY.
* MRAM part: u32 iss_ofs, u32 rnd_ofs; at iss_ofs: u32 num_sit, dls_ofs, sit_ofs, seq_ofs
  (relative to iss_ofs).  SIT = 0x18 bytes (note = bank<<8|key, vol, rnd_no, flag
  0x2000 = chained with the next SIT, 0x8000 = dummy, 0x4 = MIDI sequence).
* DLS = Nintendo SYN wavetable: hdr {x0, inst, rgn, art, sample, adpcm} ->
  WTINST u16 keyRegion[] ; WTREGION 0x18 ; WTSAMPLE 0x10 {fmt,rate,offset(nibbles),length(samples),
  adpcmIndex} ; WTADPCM 0x2E {coef[16], gain, ps, yn1, yn2, lps, lyn1, lyn2}.
* Random groups: rnd table at rnd_ofs: u32 ofs[g] -> {u16 num, u16 last, u16 no[num]}.
"""
import os, struct, subprocess, sys, wave, math, array

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # re3_w3d
DTK = os.path.join(ROOT, 'tools', 'dtk')
RVZ = os.path.join(os.path.dirname(ROOT), 'Resident Evil 4 (USA) (Disc 1)',
                   'Resident Evil 4 (USA) (Disc 1).rvz')
CACHE = os.path.join(ROOT, 'extracted')
OUT = os.path.join(ROOT, 'out', 'sonidos')
BLK_NAMES = {0: 'CORE', 1: 'PL', 2: 'WEP', 3: 'BGM0', 4: 'BGM1', 5: 'FOOT', 6: 'ROOM', 7: 'DOOR', 8: 'ENEMY'}


def disc_file(path):
    """path like 'St1/r100.das'; returns bytes, extracting from the rvz on first use."""
    local = os.path.join(CACHE, path)
    if not os.path.exists(local):
        os.makedirs(os.path.dirname(local), exist_ok=True)
        subprocess.run([DTK, 'vfs', 'cp', f'{RVZ}:files/{path}', os.path.dirname(local) + '/'],
                       check=True, stdout=subprocess.DEVNULL)
    return open(local, 'rb').read()


def walk_header(d, base=0, out=None):
    out = [] if out is None else out
    o = base + 0x20
    while o + 0x20 <= len(d):
        t, sz, dest, ofs, st, sa, sn, _ = struct.unpack('>iIIIiiII', d[o:o + 0x20])
        if t == -1:
            break
        if t == 4:
            walk_header(d, base + ofs, out)
        elif t in (1, 2):
            out.append((t, st, sa, base + ofs, sz))
        o += 0x20
    return out


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


class Bank:
    def __init__(self, mram, aram, name=''):
        self.name = name
        self.m = mram
        self.a = aram
        iss, self.rnd_ofs = struct.unpack('>II', mram[:8])
        self.num, dls, sit, seq = struct.unpack('>IIII', mram[iss:iss + 16])
        self.dls = iss + dls
        self.sit_ofs = iss + sit
        h = struct.unpack('>6I', mram[self.dls:self.dls + 24])
        self.inst_ofs, self.rgn_ofs, self.art_ofs, self.smp_ofs, self.adp_ofs = [self.dls + x for x in h[1:]]

    def sit(self, n):
        o = self.sit_ofs + n * 0x18
        f = struct.unpack('>HbbbbbbbbHHBBBbbbBBH', self.m[o:o + 0x18])
        keys = ('note', 'voice_start', 'voice_num', 'prio', 'pan', 'vol', 'aux_a', 'aux_b', 'curve_no',
                'pitch_l', 'pitch_h', 'inner_vol', 'xF', 'srd_type', 'span', 'svol', 'rnd_no', 'se_flag',
                'wall_vol', 'flag')
        return dict(zip(keys, f))

    def rnd_group(self, g):
        if g == 0 or self.rnd_ofs == 0:
            return []
        tbl = self.rnd_ofs
        o = struct.unpack('>I', self.m[tbl + 4 * g:tbl + 4 * g + 4])[0]
        if o == 0:
            return []
        num = struct.unpack('>H', self.m[tbl + o:tbl + o + 2])[0]
        return list(struct.unpack(f'>{num}H', self.m[tbl + o + 4:tbl + o + 4 + 2 * num]))

    def region(self, note):
        inst = self.inst_ofs + (note >> 8) * 256
        ri = struct.unpack('>H', self.m[inst + 2 * (note & 0xFF):inst + 2 * (note & 0xFF) + 2])[0]
        o = self.rgn_ofs + ri * 0x18
        un, kg, ft, attn, ls, ll, ai, si = struct.unpack('>BBhiIIII', self.m[o:o + 0x18])
        return dict(index=ri, unity=un, fine=ft, attn=attn, loop_start=ls, loop_len=ll, art=ai, sample=si)

    def sample(self, si):
        o = self.smp_ofs + si * 0x10
        fmt, rate, off, length, ai = struct.unpack('>HHIIH', self.m[o:o + 14])
        return dict(format=fmt, rate=rate, offset=off, length=length, adpcm=ai)

    def num_samples(self):
        return (self.adp_ofs - self.smp_ofs) // 0x10

    def coefs(self, ai):
        o = self.adp_ofs + ai * 0x2E
        v = struct.unpack('>23H', self.m[o:o + 0x2E])
        return [s16(x) for x in v[:16]], v

    def decode_sample(self, si):
        s = self.sample(si)
        coef, _ = self.coefs(s['adpcm'])
        return dsp_decode(self.a, s['offset'] // 2, s['length'], coef), s['rate']


def dsp_decode(buf, start, nsamples, coef):
    out = array.array('h')
    h1 = h2 = 0
    pos = start
    while len(out) < nsamples and pos + 8 <= len(buf):
        ps = buf[pos]
        pred = (ps >> 4) & 7
        scale = 1 << (ps & 0xF)
        c1, c2 = coef[pred * 2], coef[pred * 2 + 1]
        for i in range(14):
            if len(out) >= nsamples:
                break
            b = buf[pos + 1 + i // 2]
            n = (b >> 4) if i % 2 == 0 else (b & 0xF)
            if n >= 8:
                n -= 16
            v = ((n * scale) << 11) + 1024 + c1 * h1 + c2 * h2
            v >>= 11
            v = -32768 if v < -32768 else 32767 if v > 32767 else v
            out.append(v)
            h2, h1 = h1, v
        pos += 8
    return out


def write_wav(path, pcm, rate, loop=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(round(rate)))
        a = array.array('h', pcm)
        if sys.byteorder == 'big':
            a.byteswap()
        w.writeframes(a.tobytes())
    if loop:  # append a 'smpl' chunk with the loop
        ls, le = loop
        smpl = struct.pack('<9I', 0, 0, int(1e9 / rate), 60, 0, 0, 0, 1, 0) + struct.pack('<6I', 0, 0, ls, le - 1, 0, 0)
        with open(path, 'r+b') as f:
            f.seek(0, 2)
            f.write(b'smpl' + struct.pack('<I', len(smpl)) + smpl)
            size = f.tell()
            f.seek(4)
            f.write(struct.pack('<I', size - 8))


def resample(pcm, src_rate, dst_rate):
    if abs(src_rate - dst_rate) < 0.5:
        return [float(x) for x in pcm]
    n = int(len(pcm) * dst_rate / src_rate)
    step = src_rate / dst_rate
    out = []
    for i in range(n):
        p = i * step
        j = int(p)
        f = p - j
        a = pcm[j] if j < len(pcm) else 0
        b = pcm[j + 1] if j + 1 < len(pcm) else 0
        out.append(a + (b - a) * f)
    return out


def sit_render(bank, no):
    """Returns (pcm, rate, info) for one SIT (pitch from unity note / fine tune applied to the rate)."""
    s = bank.sit(no)
    r = bank.region(s['note'])
    smp = bank.sample(r['sample'])
    pcm, rate = bank.decode_sample(r['sample'])
    cents = ((s['note'] & 0xFF) - r['unity']) * 100 + r['fine']
    # SIT random pitch pitch_l..pitch_h in cents (snd_sub0 Snd_get_rnd_pitch): fixed when equal,
    # otherwise the middle of the range.
    cents += (s16(s['pitch_l']) + s16(s['pitch_h'])) / 2
    eff = rate * 2 ** (cents / 1200)
    loop = (r['loop_start'], r['loop_start'] + r['loop_len']) if r['loop_len'] else None
    return pcm, eff, dict(sit=s, rgn=r, smp=smp, cents=cents, loop=loop)


def chain(bank, no):
    """SIT numbers played by one request (flag 0x2000 chains to the next SIT)."""
    out = []
    while no < bank.num:
        s = bank.sit(no)
        if s['flag'] & 0x8000:
            break
        out.append(no)
        if not (s['flag'] & 0x2000):
            break
        no += 1
    return out


def render_se(bank, no, rate_out=32000):
    """Mixes the chained SITs of SE `no` (an int, or a list of SE numbers requested together:
    each SIT plays once, since every SIT owns a fixed voice slot) into stereo at rate_out: gain = SIT vol / 127 * region
    attenuation, constant-power pan from the SIT pan (0..127, 64 centre; < 0 = centre).
    Returns a list of (L, R) frames."""
    L, Rr = [], []
    sits = []
    for q in (no if isinstance(no, (list, tuple)) else [no]):
        sits += [n for n in chain(bank, q) if n not in sits]
    for n in sits:
        pcm, eff, info = sit_render(bank, n)
        s = info['sit']
        if s['flag'] & 0x4:
            continue  # MIDI sequence SE, not a single sample
        g = (s['vol'] if s['vol'] >= 0 else 127) / 127.0
        g *= 10 ** ((info['rgn']['attn'] / 65536.0) / 200.0)  # attn is 0.1 dB * 65536 (SYN)
        pan = s['pan'] if s['pan'] >= 0 else 64
        a = (pan / 127.0) * math.pi / 2
        gl, gr = g * math.cos(a) * math.sqrt(2), g * math.sin(a) * math.sqrt(2)
        x = resample(pcm, eff, rate_out)
        if len(x) > len(L):
            L += [0.0] * (len(x) - len(L))
            Rr += [0.0] * (len(x) - len(Rr))
        for i, v in enumerate(x):
            L[i] += v * gl
            Rr[i] += v * gr
    peak = max([abs(v) for v in L + Rr] or [0])
    k = 32767 / peak if peak > 32767 else 1.0
    return [(int(round(l * k)), int(round(r * k))) for l, r in zip(L, Rr)]


def write_wav_stereo(path, frames, rate):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a = array.array('h', [v for f in frames for v in f])
    if sys.byteorder == 'big':
        a.byteswap()
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())


def load_bank(path, blk_type):
    d = disc_file(path)
    parts = walk_header(d)
    mram = aram = None
    for t, st, sa, ofs, sz in parts:
        if st == blk_type:
            if t == 1:
                mram = d[ofs:ofs + sz]
            else:
                aram = d[ofs:ofs + sz]
    if mram is None:
        raise SystemExit(f'{path}: no sound block {blk_type}')
    return Bank(mram, aram, f'{path}:{BLK_NAMES.get(blk_type)}')


def dump_bank(bank, outdir):
    """Every SIT (the whole bank) as seNNN_*.wav plus a listing."""
    os.makedirs(outdir, exist_ok=True)
    lines = [f'# {bank.name}: {bank.num} SITs, {bank.num_samples()} samples',
             'se   flag  note  vol rnd  chain  sample rate   len(s)  loop  rms']
    for no in range(bank.num):
        s = bank.sit(no)
        if s['flag'] & 0x8000:
            lines.append(f'{no:3d} {s["flag"]:04x} dummy')
            continue
        if s['flag'] & 0x4:
            lines.append(f'{no:3d} {s["flag"]:04x} seq (MIDI) note {s["note"]:04x}')
            continue
        pcm, eff, info = sit_render(bank, no)
        rms = math.sqrt(sum(v * v for v in pcm) / max(1, len(pcm)))
        fn = os.path.join(outdir, f'se{no:03d}.wav')
        write_wav(fn, pcm, eff, info['loop'])
        grp = bank.rnd_group(s['rnd_no'])
        lines.append(f'{no:3d} {s["flag"]:04x} {s["note"]:04x} {s["vol"]:4d} {s["rnd_no"]:3d}'
                     f'  {"+" if s["flag"] & 0x2000 else " "}      {info["rgn"]["sample"]:3d}  {eff:7.0f} '
                     f'{len(pcm) / eff:6.3f}  {"y" if info["loop"] else "-"}  {rms:6.0f}'
                     + (f'  rnd{s["rnd_no"]}={grp}' if grp else ''))
    open(os.path.join(outdir, 'listado.txt'), 'w').write('\n'.join(lines) + '\n')
    return lines


def main():
    os.makedirs(OUT, exist_ok=True)
    wep = load_bank('em/wep02.drs', 2)   # WEP block of Leon's starting handgun (weapon_no 2, cObjRuger)
    wep1 = load_bank('em/wep01.drs', 2)  # wep01 (cObjFn57), kept for comparison
    pl = load_bank('em/pl00.drs', 1)     # PL block (Leon)
    foot = load_bank('St1/r100.das', 5)  # FOOT block of room r100 (village outskirts path)
    for b, sub in ((wep, 'banco_wep02'), (wep1, 'banco_wep01'), (pl, 'banco_pl00'), (foot, 'banco_foot_r100')):
        dump_bank(b, os.path.join(OUT, sub))

    named = []
    # Leon's starting handgun is weapon_no 2 = module wep02 (cObjRuger). moveFire
    # (src/wep/objRuger.cpp:97-99) requests WEP 0, 1 and 2 (weapon_type 0; 0x18 otherwise, :102).
    # Chained SITs (flag 0x2000) each own a fixed voice slot, so every SIT sounds once.
    named += [('disparo_pistola.wav', render_se(wep, [0, 1, 2])),
              ('disparo_pistola_tipo1.wav', render_se(wep, 0x18)),     # objRuger.cpp:102 (weapon_type != 0)
              ('pistola_vacia_click.wav', render_se(wep, 0x17)),      # pl_handgun.cpp:308
              ('pistola_recarga.wav', render_se(wep, 0x16)),          # objRuger.cpp:~150-164 (reload lv0)
              ('pistola_recarga_lv1.wav', render_se(wep, 0x20)),
              ('pistola_recarga_lv2.wav', render_se(wep, 0x21)),
              ('pistola_desenfundar.wav', render_se(pl, 0x28)),       # pl_handgun.cpp:160
              ('pistola_desenfundar_alt.wav', render_se(pl, 0x29)),   # pl_handgun.cpp:158 (m_Work2 == 1)
              ('casquillo_suelo.wav', render_se(wep, 0xF)),           # snd.cpp wepSeCheck (0xF + cartridge_type)
              ('cuchillo_tajo.wav', render_se(pl, 3))]                # the knife slash: PL 3 on frame 3
    # The previously assumed wep01 (Blacktail, objFn57.cpp:96-97: WEP 0 then 2) kept for reference.
    named += [('disparo_pistola_wep01.wav', render_se(wep1, [0, 2])),
              ('pistola_vacia_click_wep01.wav', render_se(wep1, 0x17)),
              ('pistola_recarga_wep01.wav', render_se(wep1, 0x16)),
              ('pistola_recarga_lv1_wep01.wav', render_se(wep1, 0x20)),
              ('pistola_recarga_lv2_wep01.wav', render_se(wep1, 0x21)),
              ('casquillo_suelo_wep01.wav', render_se(wep1, 0xF))]
    for j, g in enumerate(pl.rnd_group(pl.sit(0x2A)['rnd_no'])):      # pl_class.cpp:856 walk rustle
        named.append((f'ropa_caminar_{j}.wav', render_se(pl, g)))
    for j, g in enumerate(pl.rnd_group(pl.sit(0x2F)['rnd_no'])):      # pl_class.cpp:863 run rustle
        named.append((f'ropa_correr_{j}.wav', render_se(pl, g)))
    # Footsteps: seqSeCtrl (pl_class.cpp:812-882) -> SndCall(5, 0..3) = walk L/R, run L/R, +30 *
    # surface se_type (footSeCheck, snd.cpp:510). Type 0 is the default (FlrSys cleared, no
    # FlrAtSetDefVal in r100/r101) = the open ground of the village rooms; types 0/1 are identical
    # in r100 and r101.
    names = ['caminar_izq', 'caminar_der', 'correr_izq', 'correr_der', 'caida_rodilla', 'caida_cuerpo']
    for k in range(6):
        named.append((f'paso_tierra_{names[k]}.wav', render_se(foot, k)))
    for t in range(1, (foot.num + 29) // 30):
        for k in range(4):
            no = t * 30 + k
            if no < foot.num and not foot.sit(no)['flag'] & 0x8000:
                named.append((f'otros_suelos/paso_suelo{t}_{names[k]}.wav', render_se(foot, no)))
    for fn, fr in named:
        write_wav_stereo(os.path.join(OUT, fn), fr, 32000)
        write_n95(os.path.join(OUT, 'n95', fn), fr, 32000, os.path.basename(fn).startswith('paso_'))
    return named


def write_n95(path, frames, rate, normalize):
    """Small copy for the Nokia N95: mono, 16-bit, 22050 Hz; footsteps normalised to -6 dBFS peak."""
    mono = [(l + r) / 2.0 for l, r in frames]
    x = resample(mono, rate, 22050)
    pk = max([abs(v) for v in x] or [0])
    if normalize and pk > 0:
        k = 32767 * 10 ** (-6 / 20) / pk
    else:
        k = 32767 / pk if pk > 32767 else 1.0
    write_wav(path, [int(round(v * k)) for v in x], 22050)


if __name__ == '__main__':
    for fn, fr in main():
        print(f'{fn:48s} {len(fr) / 32000:.3f}s')
