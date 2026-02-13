.PHONY: docs clean

docs:
	@cd docs && npm install
	@cd docs && npm run start
	
clean:
	@cd docs && npm run clear
	@cd docs && npm cache clean --force
	@rm -rf docs/node_modules
