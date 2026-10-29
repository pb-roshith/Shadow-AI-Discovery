export default [
  {id:'credit-dossier', name:'Credit Dossier', description:'Upload a credit memo and ask questions grounded in its pages and paragraphs.', kind:'memo', action:'Ask about memo', port:8101},
  {id:'policy-intelligence', name:'Policy Intelligence', description:'Check a company loan request against a bank policy, with clause-by-clause findings.', kind:'policy', action:'Check bank policy', port:8102},
  {id:'loan-risk-classifier', name:'Loan Risk Classifier', description:'Enter loan and borrower values for a local Ollama risk score and explanation.', kind:'classifier', action:'Assess loan risk', port:8103},
  {id:'customer-assistant', name:'Customer Assistant', description:'Chat with Gemini, Mistral or OpenAI.', kind:'chat', action:'Send message', port:8105},
  {id:'creditdb-MCP', name:'creditdb-MCP', description:'Inspect the loan database MCP server and its available read and write tools.', kind:'mcp', action:'View tools', port:8765},
];
