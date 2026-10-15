// Zeichnet alle Abzeichen: Sechseck-Rahmen + Icon von game-icons.net (CC BY 3.0).
// Eingabe: JSON-Liste von `python -m services.achievements` auf stdin.
// Ausgabe: assets/badges/<file>.png
import { Resvg } from '@resvg/resvg-js'
import { dirname, join } from 'node:path'

type Style = { light: string; mid: string; dark: string; ink: string; rim?: [string, string]; grain?: boolean }
const STYLES: Record<string, Style> = {
  holz: { light: '#E2B17D', mid: '#9C6534', dark: '#5A3517', ink: '#4A2A10', grain: true },
  bronze: { light: '#F0B489', mid: '#B8693A', dark: '#6E3A1C', ink: '#5A2C12' },
  silber: { light: '#F4F6F8', mid: '#AEB6BE', dark: '#5E666E', ink: '#4A5158' },
  gold: { light: '#FFE08A', mid: '#D9A12B', dark: '#7A5410', ink: '#5E400A' },
  // Einmalige: königsblau mit goldenem Rand. Geheime: dunkles Violett.
  einmalig: { light: '#6E8FE0', mid: '#2B4C9B', dark: '#15285A', ink: '#FFE08A', rim: ['#FFE08A', '#D9A12B'] },
  geheim: { light: '#9A6FD0', mid: '#4B2A7A', dark: '#241040', ink: '#F4F6F8' },
}

const here = dirname(new URL(import.meta.url).pathname)
const out = join(here, '..', '..', 'assets', 'badges')

const hexagon = (r: number) =>
  Array.from({ length: 6 }, (_, i) => {
    const a = ((-90 + i * 60) * Math.PI) / 180
    return `${(128 + r * Math.cos(a)).toFixed(1)},${(128 + r * Math.sin(a)).toFixed(1)}`
  }).join(' ')

async function badge(icon: string, style: Style): Promise<string> {
  const raw = await Bun.file(join(here, 'icons', `${icon}.svg`)).text()
  const inner = raw.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '').replaceAll('currentColor', style.ink)
  const [rimLight, rimMid] = style.rim ?? [style.light, style.mid]
  const grain = style.grain
    ? [52, 78, 104, 150, 176, 204]
        .map((y, i) => `<path d="M20 ${y} C 70 ${y - 10} 110 ${y + 12} 160 ${y} S 230 ${y - 8} 240 ${y + 4}" stroke="${style.dark}" stroke-opacity="0.28" stroke-width="${[3, 2, 4, 2, 3, 2][i]}" fill="none"/>`)
        .join('')
    : ''
  return `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${rimLight}"/><stop offset="0.55" stop-color="${rimMid}"/><stop offset="1" stop-color="${style.dark}"/></linearGradient>
    <linearGradient id="face" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${style.light}"/><stop offset="1" stop-color="${style.mid}"/></linearGradient>
    <clipPath id="inner"><polygon points="${hexagon(94)}"/></clipPath>
  </defs>
  <polygon points="${hexagon(120)}" fill="url(#rim)"/>
  <polygon points="${hexagon(100)}" fill="${style.dark}" opacity="0.35"/>
  <polygon points="${hexagon(94)}" fill="url(#face)"/>
  <g clip-path="url(#inner)">${grain}</g>
  <polygon points="${hexagon(94)}" fill="none" stroke="#FFFFFF" stroke-opacity="0.3" stroke-width="3"/>
  <svg x="66" y="66" width="124" height="124" viewBox="0 0 512 512">${inner}</svg>
</svg>`
}

const specs: { file: string; icon: string; style: string }[] = JSON.parse(await Bun.stdin.text())
for (const spec of specs) {
  const style = STYLES[spec.style]
  if (!style) throw new Error(`unbekannter Stil ${spec.style}`)
  const png = new Resvg(await badge(spec.icon, style), { fitTo: { mode: 'width', value: 160 } }).render().asPng()
  await Bun.write(join(out, spec.file), png)
}
console.log(`${specs.length} Abzeichen nach ${out}`)
