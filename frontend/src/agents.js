// The GIU agents, in one place for the start screen, the chat screen and the coming-soon
// page. Keys, names and who may use them must match backend/app/agents/directory.py.
// `ready: false` agents are not built yet and open the coming-soon page. Ready agents
// also say how the chat screen looks for them (subtitle, examples, placeholder, CV button).
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
    key: "internship_career",
    name: "Internship & Career Assistant",
    handles: "Internships, the career fair, CV review, interviews, skills and career paths",
    userTypes: ["student"],
    ready: true,
    subtitle: "GIU career information and general career advice",
    welcome: "Ask about internships, the GIU Career Fair, your CV or interviews, or try one of these:",
    placeholder: "Ask about internships, CVs, interviews, career paths...",
    examples: [
      "When was the GIU Career Fair 2025?",
      "How long is the GIU Internship Semester?",
      "How do I prepare for an interview?",
      "What skills do I need as a computer science student?",
    ],
    cvReview: true, // shows the "Analyze my CV" button
  },
  {
    key: "labs_research",
    name: "Labs & Research Assistant",
    handles: "Lab access, supervisors, equipment, research resources, campus offices",
    userTypes: ["student", "staff"],
    ready: true,
    subtitle: "Answers from official GIU documents",
    welcome: "Ask anything about GIU labs, rooms and offices, or try one of these:",
    placeholder: "Ask about labs, offices, rooms, research funding...",
    examples: [
      "Where is the AI lab?",
      "Where is the Admission Office?",
      "How do I pay my tuition fees?",
      "Where is the gym?",
    ],
  },
];

export function findAgent(key) {
  return AGENTS.find((agent) => agent.key === key);
}
