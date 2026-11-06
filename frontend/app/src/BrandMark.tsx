type BrandMarkProps = {
  className?: string
}

export default function BrandMark({ className = '' }: BrandMarkProps) {
  return (
    <span className={`reactant-mark ${className}`.trim()} aria-hidden="true">
      <span className="reactant-mark-bond reactant-mark-bond-left" />
      <span className="reactant-mark-bond reactant-mark-bond-right" />
      <span className="reactant-mark-node reactant-mark-node-top" />
      <span className="reactant-mark-node reactant-mark-node-left" />
      <span className="reactant-mark-node reactant-mark-node-right" />
    </span>
  )
}
