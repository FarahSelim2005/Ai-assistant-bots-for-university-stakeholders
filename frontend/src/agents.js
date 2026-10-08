// The four GIU agents, in one place for the start screen and the coming-soon page.
// Keys, names and who may use them must match backend/app/agents/directory.py.
// `ready: false` agents are not built yet and open the coming-soon page.
export const AGENTS = [
  {
    key: "graduation_advising",
    name: "Graduation & Advising Assistant",
    handles: "Degree requirements, course planning, graduation timeline and advising",
    userTypes: ["student", "staff"],
    ready: false,
  },
  {
    key: "hr_policies",
    name: "HR & Policies Assistant",
    handles: "Leave types, benefits, staff policies and complaints",
    userTypes: ["staff"],
    ready: false,
  },
  {
    key: "orientation",
    name: "Orientation Assistant",
    handles: "Campus map, buildings, registration and student services",
    userTypes: ["student", "staff"],
    ready: false,
  },
  {
    key: "labs_research",
    name: "Labs & Research Assistant",
    handles: "Lab access, supervisors, equipment, research resources, campus offices",
    userTypes: ["student", "staff"],
    ready: true,
  },
];

export function findAgent(key) {
  return AGENTS.find((agent) => agent.key === key);
}
