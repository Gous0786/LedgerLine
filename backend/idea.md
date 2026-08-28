Multi-source agentic payment reconciliation

vague idea:(DONT IMPEMENT ANYTHING YET FROM THIS)
- Multiple csv uploads 
- small chunks ingested from each one by an Analyser agent to make a mental graph of payments direction
- this mental model is saved in the memory with primiary sources(maybe orders) marked and final settlement sources(maybe banks statement) marked
-Now the orchestrator agent will analyse the user queries , if its to reconcile all the payments , it will understand the payment direction graph ,takes a batch from the primary sources ,and start reconciling them. While doing it , it will also learn from the patterns that may help imporoving the retrieval for next batches and add them to memory , if the query is just about the single transaction or state , it will pull out infromation reagardign that transaction and will give the answers.
- Now agent will pick out batches, perform queries using tool or sql on the exisiting data, then tires to reconcile each one. Autoreconcile one with confidencee score over threshold and ask for human intervention with the data for less confidence reconciliation , for least confident (the one which cant be reconciled , it will display that , then with a click to mark for review / unreconciled ) add to the reconciled list
the reconciled list is the reconciled record of each transaction (with events in order for each) source for audit 

My aim is to reconcile every data be agents while also optimising the cost