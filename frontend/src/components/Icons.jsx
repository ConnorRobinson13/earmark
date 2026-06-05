const PATHS = {
  home:  <path d="M2 7l6-5 6 5v7a1 1 0 0 1-1 1h-3v-5h-4v5H3a1 1 0 0 1-1-1V7z" />,
  plus:  <path d="M8 3v10M3 8h10" />,
  inbox: <><path d="M2 9l1.5-6h9L14 9v4a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V9z" /><path d="M2 9h4l1 1.5h2L10 9h4" /></>,
  flag:  <path d="M3 14V2M3 3h9l-1.5 3L12 9H3" />,
  plan:  <><rect x="2" y="3" width="12" height="11" rx="1" /><path d="M2 6h12M5 2v3M11 2v3" /></>,
  cog:   <><circle cx="8" cy="8" r="2" /><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6L13 13M13 3l-1.4 1.4M4.4 11.6L3 13" /></>,
  chev_l:<path d="M10 3l-5 5 5 5" />,
  chev_r:<path d="M6 3l5 5-5 5" />,
  chev_d:<path d="M3 6l5 5 5-5" />,
  check: <path d="M3 8l3.5 3.5L13 5" />,
  x:     <path d="M4 4l8 8M12 4l-8 8" />,
  sync:  <path d="M2 8a6 6 0 0 1 10-4.5M14 8a6 6 0 0 1-10 4.5M11 2v3h3M5 14v-3H2" />,
  search:<><circle cx="7" cy="7" r="4.5" /><path d="M11 11l3 3" /></>,
  spark: <path d="M8 2l1.5 4.5L14 8l-4.5 1.5L8 14l-1.5-4.5L2 8l4.5-1.5L8 2z" />,
  wave:  <path d="M1 8c1.5 0 1.5-3 3-3s1.5 3 3 3 1.5-3 3-3 1.5 3 3 3 1.5-3 3-3" />,
  trash: <path d="M3 4h10M6 4V2.5A.5.5 0 0 1 6.5 2h3a.5.5 0 0 1 .5.5V4M5 4l.5 9a1 1 0 0 0 1 .9h3a1 1 0 0 0 1-.9L11 4" />,
}

export function Icon({ name, size = 16, className = 'ico' }) {
  const path = PATHS[name]
  if (!path) return null
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16"
      fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {path}
    </svg>
  )
}
