// The university's logo, or (without one) its short name on its brand colour.
import { tenant } from "../tenant.js";

export default function BrandLogo({ className }) {
  const { logo_url: logo, name, short_name: shortName } = tenant();
  if (logo) return <img src={logo} alt={name} className={className} />;
  return <span className={`${className} text-logo`} role="img" aria-label={name}>{shortName}</span>;
}
