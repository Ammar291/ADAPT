import { tr } from ".";

/** Presentation labels only; never feed locale-dependent strings into a graph layout. */
export function graphA11y() {
  return {
    "node.a11yDescription.default": tr("graph.keyboard"),
    "node.a11yDescription.keyboardDisabled": tr("graph.openDetails"),
    "edge.a11yDescription.default": tr("graph.connection"),
    "controls.ariaLabel": tr("graph.controls"),
    "controls.zoomIn.ariaLabel": tr("graph.zoomIn"),
    "controls.zoomOut.ariaLabel": tr("graph.zoomOut"),
    "controls.fitView.ariaLabel": tr("graph.fit"),
    "controls.interactive.ariaLabel": tr("graph.interaction"),
    "minimap.ariaLabel": tr("graph.minimap"),
    "handle.ariaLabel": tr("graph.connection"),
  };
}
